import datetime
import importlib
import json
import logging
import random
import string
import sys
import traceback
import uuid

try:
    import uwsgi
except ImportError:
    uwsgi = None

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.db import close_old_connections
from django.db.models import Q, signals
from django.utils.translation import gettext_lazy as _

from cryptography.hazmat.primitives.ciphers import (
    Cipher, algorithms, modes)
from cryptography.hazmat.backends import default_backend

from djcall.models import Caller

from model_utils.managers import (
    InheritanceManagerMixin,
    InheritanceQuerySetMixin,
)

from .exceptions import PermanentError, TemporaryError

logger = logging.getLogger('djtezos')


SETTINGS = dict(
    PROVIDERS=(
        ('djtezos.tezos.Provider', 'Tezos'),
        ('djtezos.fake.Provider', 'Test'),
        ('djtezos.fake.FailDeploy', 'Test that fails deploy'),
        ('djtezos.fake.FailWatch', 'Test that fails watch'),
    )
)
SETTINGS.update(getattr(settings, 'DJBLOCKCHAIN', {}))


KEY = settings.SECRET_KEY.encode('utf8')[:32]
IV = settings.SECRET_KEY.encode('utf8')[-16:]


def cipher():
    return Cipher(
        algorithms.AES(KEY),
        modes.CBC(IV),
        backend=default_backend()
    )


def encrypt(secret):
    encryptor = cipher().encryptor()
    return encryptor.update(secret) + encryptor.finalize()


def decrypt(secret):
    decryptor = cipher().decryptor()
    return decryptor.update(secret) + decryptor.finalize()


class Account(models.Model):
    created_at = models.DateTimeField(
        null=True,
        blank=True,
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        null=True,
        blank=True,
        auto_now=True,
    )
    address = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )
    blockchain = models.ForeignKey(
        'Blockchain',
        on_delete=models.CASCADE,
    )
    crypted_key = models.BinaryField()
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    def __str__(self):
        return self.address

    @property
    def provider(self):
        return self.blockchain.provider

    @property
    def private_key(self):
        return decrypt(self.crypted_key) if self.crypted_key else None

    @property
    def to_spool(self):
        """Return transactions pending for action"""
        return self.transactions_sent.exclude(
            state__in=(
                'held',
                'done',
                'deploy-aborted',
                'watch-aborted',
                'postdeploy-aborted',
            ),
        ).order_by('created_at').select_subclasses()

    @property
    def caller(self):
        if '_djcall_caller' not in self.__dict__:
            # get existing sender for this sender or create a new one
            self._djcall_caller = Caller.objects.get_or_create(
                callback='djtezos.models.sender_queue',
                kwargs=dict(pk=str(self.pk)),
            )[0]
        return self._djcall_caller

    def spool(self, force=False):
        if not force and self.caller.running:
            return
        self.caller.spool('blockchain')

    def get_balance(self):
        return self.provider.get_balance(self.address, self.private_key)


def sender_queue(pk):
    acc = Account.objects.filter(pk=pk).first()
    if not acc:
        logger.error(f'{pk} does not exist anymore')
        return

    tx = acc.to_spool.first()

    if not tx:
        logger.info(f'Account {pk} has no pending transaction')
        return

    if tx.state in ('deploy', 'deploying'):
        tx.deploy_state()

    elif tx.state in ('watch', 'watching'):
        tx.watch_state()

    elif tx.state in ('postdeploy', 'postdeploying'):
        tx.postdeploy_state()

    # restart myself until I shut down by myself because my work is done
    acc.spool(force=True)


def account_wallet(sender, instance, **kwargs):
    if instance.crypted_key or not instance.owner:
        return

    passphrase = ''.join(
        random.choice(string.ascii_letters) for i in range(42)
    )

    instance.address, private_key = (
        instance.blockchain.provider.create_wallet(passphrase)
    )

    instance.crypted_key = encrypt(private_key)
signals.pre_save.connect(account_wallet, sender=Account)


class Blockchain(models.Model):
    name = models.CharField(max_length=100)
    endpoint = models.CharField(max_length=255)
    explorer = models.CharField(max_length=255, null=True, blank=True)
    provider_class = models.CharField(
        max_length=255,
        choices=SETTINGS['PROVIDERS'],
        default='djtezos.fake.Provider',
    )
    confirmation_blocks = models.IntegerField(default=0)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    @property
    def provider(self):
        parts = self.provider_class.split('.')
        mod = importlib.import_module(
            '.'.join(parts[:-1])
        )
        return getattr(mod, parts[-1])(self)


class TransactionQuerySet(InheritanceQuerySetMixin, models.QuerySet):
    def for_user(self, user):
        return self.filter(
            Q(sender__owner=user) | Q(receiver__owner=user),
        ).distinct()


class TransactionManager(InheritanceManagerMixin, models.Manager):
    def get_queryset(self):
        return TransactionQuerySet(self.model)


class Transaction(models.Model):
    id = models.UUIDField(
        primary_key=True,
        editable=False,
        default=uuid.uuid4
    )
    sender = models.ForeignKey(
        'Account',
        related_name='transactions_sent',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )
    receiver = models.ForeignKey(
        'Account',
        related_name='transactions_received',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(
        null=True,
        blank=True,
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        null=True,
        blank=True,
        auto_now=True,
    )
    txhash = models.CharField(
        unique=True,
        max_length=255,
        null=True,
        blank=True,
    )
    gasprice = models.BigIntegerField(blank=True, null=True)
    gas = models.BigIntegerField(blank=True, null=True)
    contract_address = models.CharField(max_length=255, null=True)
    contract_name = models.CharField(max_length=100, null=True)
    contract_source = models.TextField(null=True, blank=True)
    contract_micheline = models.JSONField(null=True, blank=True, default=list)
    contract = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='call_set',
    )
    function = models.CharField(max_length=100, null=True, blank=True)
    args = models.JSONField(null=True, default=list, blank=True)
    amount = models.PositiveIntegerField(
        default=0,
        blank=True,
        help_text='Amount in xTZ',
    )

    STATE_CHOICES = (
        ('held', _('Held')),
        ('deploy', _('To deploy')),
        ('deploying', _('Deploying')),
        ('deploy-aborted', _('Deploy aborted')),
        ('watch', _('To watch')),
        ('watching', _('Watching')),
        ('watch-aborted', _('Watch aborted')),
        ('postdeploy', _('To post-deploy')),
        ('postdeploying', _('Post-deploying')),
        ('postdeploy-aborted', _('Postdeploy aborted')),
        ('done', _('Finished')),
    )
    state = models.CharField(
        choices=STATE_CHOICES,
        default='held',
        max_length=200,
        db_index=True,
    )
    error = models.TextField(blank=True)
    history = models.JSONField(default=list)
    states = [i[0] for i in STATE_CHOICES]

    objects = TransactionManager()

    def __str__(self):
        return self.txhash or self.contract_name or str(self.pk)

    @property
    def blockchain(self):
        if self.sender:
            return self.sender.blockchain

    @property
    def explorer_link(self):
        return self.blockchain.explorer.format(self.txhash)

    @property
    def provider(self):
        return self.sender.blockchain.provider

    def save(self, *args, **kwargs):
        if (
            not self.amount
            and not self.function
            and not self.contract_micheline
        ):
            raise ValidationError('Requires amount, function or micheline')

        if self.contract_id and not self.contract_name:
            self.contract_name = self.contract.contract_name

        if self.contract_id and not self.contract_address:
            self.contract_address = self.contract.contract_address

        if self.state not in self.states:
            raise Exception('Invalid state', self.state)

        result = super().save(*args, **kwargs)
        if self.sender_id:
            self.sender.spool()
        return result

    def call(self, **kwargs):
        return Transaction.objects.create(
            contract=self,
            **kwargs
        )

    def deploy_state(self):
        self.state_set('deploying')
        try:
            self.txhash = self.deploy()
        except Exception as exception:
            self.error = str(exception)
            if isinstance(exception, PermanentError):
                logger.exception(f'{self} deploy permanent error {self.error}')
                self.state_set('deploy-aborted')
            else:
                if isinstance(exception, TemporaryError):
                    logger.info(f'{self} temporary error: {self.error}')
                else:
                    logger.exception(f'{self} deploy exception: {self.error}')
                self.state_set('deploy')
        else:
            self.error = ''
            self.state_set('watch')

    def watch_state(self):
        self.state_set('watching')
        try:
            self.watch()
        except Exception as exception:
            self.error = str(exception)
            if isinstance(exception, PermanentError):
                logger.exception(f'{self} watch permanent error {self.error}')
                self.state_set('watch-aborted')
            else:
                if isinstance(exception, TemporaryError):
                    logger.info(f'{self} temporary error: {self.error}')
                else:
                    logger.exception(f'{self} watch exception: {self.error}')
                self.state_set('watch')
        else:
            self.error = ''
            self.state_set('postdeploy')

    def watch(self):
        self.sender.blockchain.provider.watch(self)

    def postdeploy_state(self):
        self.state_set('postdeploying')
        try:
            self.postdeploy()
        except Exception as exception:
            self.error = str(exception)
            if isinstance(exception, PermanentError):
                logger.exception(f'{self} postdeploy permanent error {self.error}')
                self.state_set('postdeploy-aborted')
            else:
                if isinstance(exception, TemporaryError):
                    logger.info(f'{self} temporary error: {self.error}')
                else:
                    logger.exception(f'{self} postdeploy exception: {self.error}')
                self.state_set('postdeploy')
        else:
            self.error = ''
            self.state_set('done')

    def postdeploy(self):
        pass

    def state_set(self, state):
        self.state = state
        self.history.append([
            self.state,
            int(datetime.datetime.now().strftime('%s')),
        ])
        self.save()
        logger.info(f'Tx({self}).state set to {self.state}')
        # ensure commit happens, is it really necessary ?
        # not sure why not
        # django.db.connection.close()
        # close_old_connections()

    def deploy(self):
        return self.provider.deploy(self)


class ContractQuerySet(TransactionQuerySet):
    def get_queryset(self):
        return super().get_queryset().filter(function=None, amount=None)


class ContractManager(TransactionManager):
    def get_queryset(self):
        return ContractQuerySet(self.model)


class Contract(Transaction):
    objects = ContractManager()

    class Meta:
        proxy = True


class CallQuerySet(TransactionQuerySet):
    def get_queryset(self):
        return super().get_queryset().exclude(function=None)


class CallManager(TransactionManager):
    def get_queryset(self):
        return CallQuerySet(self.model)


class Call(Transaction):
    objects = CallManager()

    class Meta:
        proxy = True


class TransferQuerySet(TransactionQuerySet):
    def get_queryset(self):
        return super().get_queryset().exclude(amount=None)


class TransferManager(TransactionManager):
    def get_queryset(self):
        return TransferQuerySet(self.model)


class Transfer(Transaction):
    class Meta:
        proxy = True
