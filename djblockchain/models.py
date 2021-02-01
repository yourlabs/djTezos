import datetime
import importlib
import random
import string
import uuid
import logging

try:
    import uwsgi
except ImportError:
    uwsgi = None

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.db import close_old_connections
from django.db.models import signals
from django.utils.translation import gettext_lazy as _

from cryptography.hazmat.primitives.ciphers import (
    Cipher, algorithms, modes)
from cryptography.hazmat.backends import default_backend

from djcall.models import Caller

from model_utils.managers import InheritanceManager

logger = logging.getLogger('djblockchain')


SETTINGS = dict(
    PROVIDERS=(
        ('djblockchain.ethereum.Provider', 'Ethereum'),
        ('djblockchain.tezos.Provider', 'Tezos'),
        ('djblockchain.fake.Provider', 'Test'),
        ('djblockchain.fake.FailDeploy', 'Test that fails deploy'),
        ('djblockchain.fake.FailWatch', 'Test that fails watch'),
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
            state__in=('held', 'done'),
        ).order_by('created_at').select_subclasses()

    @property
    def caller(self):
        if '_djcall_caller' not in self.__dict__:
            # get existing sender for this sender or create a new one
            self._djcall_caller = Caller.objects.get_or_create(
                callback='djblockchain.models.sender_queue',
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

    if tx.error:
        logger.info(f'Transaction {tx} has an error, aborting')
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


def user_wallets(sender, instance, **kwargs):
    for blockchain in Blockchain.objects.all():
        account, created = Account.objects.get_or_create(
            owner=instance, blockchain=blockchain)

        if not created:
            continue

        # equisafe only, to remove
        if not getattr(instance, 'is_company', None):
            # provision only companies
            continue

        if 'carthagenet' not in blockchain.endpoint and 'tzlocal' not in blockchain.name:
            # provision only on carthagenet or tzlocal
            continue

        if blockchain.id != instance.blockchain_id:
            # provision only companies that are on carthagenet or tzlocal
            continue

        instance.blockchain.provider.provision(account.address)
#signals.post_save.connect(user_wallets, sender=get_user_model())


class Block(models.Model):
    blockchain = models.ForeignKey(
        'Blockchain',
        on_delete=models.CASCADE,
    )
    number = models.PositiveIntegerField()


class Blockchain(models.Model):
    name = models.CharField(max_length=100)
    endpoint = models.CharField(max_length=255)
    explorer = models.CharField(max_length=255, null=True, blank=True)
    provider_class = models.CharField(
        max_length=255,
        choices=SETTINGS['PROVIDERS'],
        default='djblockchain.fake.Provider',
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


def blockchain_wallets(sender, instance, created, **kwargs):
    if created:
        for user in get_user_model().objects.all():
            Account.objects.get_or_create(owner=user, blockchain=instance)
#signals.post_save.connect(blockchain_wallets, sender=Blockchain)


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
    block = models.ForeignKey(
        'Block',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    gasprice = models.BigIntegerField(blank=True, null=True)
    gas = models.BigIntegerField(blank=True, null=True)
    contract_address = models.CharField(max_length=255, null=True)
    contract_name = models.CharField(max_length=100, null=True)
    contract = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='call_set',
    )
    function = models.CharField(max_length=100, null=True, blank=True)
    args = models.JSONField(null=True, default=list)

    STATE_CHOICES = (
        ('held', _('Held')),
        ('deploy', _('To deploy')),
        ('deploying', _('Deploying')),
        ('watch', _('To watch')),
        ('watching', _('Watching')),
        ('postdeploy', _('To post-deploy')),
        ('postdeploying', _('Post-deploying')),
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

    objects = InheritanceManager()

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
        if self.state not in self.states:
            raise Exception('Invalid state', self.state)
        result = super().save(*args, **kwargs)
        if self.error:
            raise Exception('Error', self.error)
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
        except Exception as e:
            # todo: attempt a certain amount
            # self.state_set('error')
            self.error = str(e)
            self.save()
        else:
            self.state_set('watch')

    def watch_state(self):
        self.state_set('watching')
        try:
            self.watch()
        except Exception as e:
            self.error = str(e)
            self.save()
        else:
            self.state_set('postdeploy')

    def watch(self):
        self.sender.blockchain.provider.watch(self)

    def postdeploy_state(self):
        self.state_set('postdeploying')
        try:
            self.postdeploy()
        except Exception as e:
            self.error = str(e)
            self.save()
        else:
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
        if self.contract_id:
            self.contract_name = self.contract.contract_name
            self.contract_address = self.contract.contract_address

        if self.function:
            return self.provider.send(
                self.sender.address,
                self.sender.private_key,
                self.contract_name,
                self.contract_address,
                self.function,
                *self.args,
            )
        else:
            return self.provider.deploy(
                self.sender.address,
                self.sender.private_key,
                self.contract_name,
                *self.args,
            )
