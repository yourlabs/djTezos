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
from django.contrib.postgres.fields import JSONField
from django.db import models
from django.db.models import signals

from cryptography.hazmat.primitives.ciphers import (
    Cipher, algorithms, modes)
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger('djblockchain')


SETTINGS = dict(
    PROVIDERS=(
        ('djblockchain.ethereum.Provider', 'Ethereum'),
        ('djblockchain.tezos.Provider', 'Tezos'),
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
        Account.objects.get_or_create(owner=instance, blockchain=blockchain)
signals.post_save.connect(user_wallets, sender=get_user_model())


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


def blockchain_wallets(sender, instance, **kwargs):
    for user in get_user_model().objects.all():
        Account.objects.get_or_create(owner=user, blockchain=instance)
signals.post_save.connect(blockchain_wallets, sender=Blockchain)


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
    accepted = models.BooleanField(
        help_text='Has this transaction been accepted by the blockchain',
        default=None,
        null=True,
    )
    status = models.BooleanField(
        help_text='Has this transaction been accepted by the blockchain',
        default=False,
        db_index=True,
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
    args = JSONField(null=True, default=list)
    hold = models.BooleanField(default=False)

    @property
    def blockchain(self):
        return self.sender.blockchain

    @property
    def explorer_link(self):
        return self.blockchain.explorer.format(self.txhash)

    @property
    def provider(self):
        return self.sender.blockchain.provider

    def watch(self, spool=True, postdeploy_kwargs=None):
        self.sender.blockchain.provider.watch(
            self,
            spool=spool,
            postdeploy_kwargs=postdeploy_kwargs or dict(),
        )

    def call(self, **kwargs):
        return Transaction.objects.create(
            contract=self,
            **kwargs
        )

    def save(self, *args, **kwargs):
        result = None
        if not self.hold and not self.txhash:
            if uwsgi:
                # WIP: ideally, we would only lock based on the tx sender address
                logger.debug(
                    f'\nsetting lock for tx {self.id} = {self} contract {self.contract} fn {self.function}\n')
                # uwsgi.lock(1)
                uwsgi.sharedarea_wlock(0)
            try:
                self.txhash = self.deploy()
            finally:
                if uwsgi:
                    logger.debug(f'\nunlocking for tx {self.id} = {self} contract {self.contract} fn {self.function}\n')
                    uwsgi.sharedarea_unlock(0)
                    # uwsgi.unlock(1)
        result = super().save(*args, **kwargs)
        if self.txhash and not self.accepted:
            self.watch()
        return result


    def postdeploy(self):
        pass

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
