import importlib
import os
import random
import string
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField
from django.db import models
from django.db.models import signals

from cryptography.hazmat.primitives.ciphers import (
    Cipher, algorithms, modes)
from cryptography.hazmat.backends import default_backend


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

    # tezos: all on same address
    #class Meta:
    #    unique_together = (
    #        ('blockchain', 'address'),
    #    )

    @property
    def provider(self):
        return self.blockchain.provider

    @property
    def private_key(self):
        return decrypt(self.crypted_key) if self.crypted_key else None


def account_wallet(sender, instance, **kwargs):
    babylon_wallets = {
        '58fc6746-5473-4535-9315-9594c7b0ccf2': (
            'tz1iqmduBYqk3sbHK35SP57DUc1U4SsrF416',
            b'\xd5\xa54\n\x8cxd*R=\x1b)\x10a\x1b\xf51\xbc\xef\xe3\xc8n\x06\xe3\xd4\xc9n\xb3\x06\x93{&\xd7\xbc^vH1\xf9\n\x07\xba\xf5&\xf8\x96\xe34,U\x18\xa1\xfa\x8apP\xd2F\xc1\xc2eR\x13%'
        ),
        '4b56613e-845a-41bf-a752-aa01315e8e83': (
            'tz1grSQDByRpnVs7sPtaprNZRp531ZKz6Jmm',
            b'0\xbb4S\xaa\x86 <J\xf7\xbe\x05\xe9\xc3\xdbRi\xc7\x8a\xb2\xb1n\xd8:\xbd\xdb\x18\\*\xb7\x00\x94\x17\x14?b\xff\x9c/A\xb3\x0e\xe0\x0b\x8cd\xd23\xfd\xa4:\xdf\x05\xeb\x82\x9c\xfd.s>\xe9\xa8\xf4K'
        ),
        'a6b07b4a-787d-440f-8ddb-96c3cc76e7a2': (
            'tz1iqmduBYqk3sbHK35SP57DUc1U4SsrF416',
            b'\xd5\xa54\n\x8cxd*R=\x1b)\x10a\x1b\xf51\xbc\xef\xe3\xc8n\x06\xe3\xd4\xc9n\xb3\x06\x93{&\xd7\xbc^vH1\xf9\n\x07\xba\xf5&\xf8\x96\xe34,U\x18\xa1\xfa\x8apP\xd2F\xc1\xc2eR\x13%'
        ),
        'a86cc89d-d8c7-415c-a6cd-2c2932f0ff62': (
            'tz1iqmduBYqk3sbHK35SP57DUc1U4SsrF416',
            b'\xd5\xa54\n\x8cxd*R=\x1b)\x10a\x1b\xf51\xbc\xef\xe3\xc8n\x06\xe3\xd4\xc9n\xb3\x06\x93{&\xd7\xbc^vH1\xf9\n\x07\xba\xf5&\xf8\x96\xe34,U\x18\xa1\xfa\x8apP\xd2F\xc1\xc2eR\x13%'
        ),
        'f60b925c-fd6b-45aa-8b03-a528c200fbc4': (
            'tz1grSQDByRpnVs7sPtaprNZRp531ZKz6Jmm',
            b'0\xbb4S\xaa\x86 <J\xf7\xbe\x05\xe9\xc3\xdbRi\xc7\x8a\xb2\xb1n\xd8:\xbd\xdb\x18\\*\xb7\x00\x94\x17\x14?b\xff\x9c/A\xb3\x0e\xe0\x0b\x8cd\xd23\xfd\xa4:\xdf\x05\xeb\x82\x9c\xfd.s>\xe9\xa8\xf4K'
        )
    }

    '''
    out of order for now:
    'tz1i7nMgiuhFyCUMFQBQuXQdWEUsFNmw4TQj',
    b'w\x95\x8b)\xd0\x81\xb7\x95\x85<*\x07\xed\xa4%\x8dR(W\xee0\x9b\xc7!(\xe9\xfb\x93\xe7AvZ\x9f\xc5\xbaI\xb3\xeb\x81gH~\x15o\xaa\xe1M\xc7h\x88*\x82\x10\xd5\xed\xc0\xac\xf7&T\x85\xe53\\'

    'tz1LfxvYmbJYGrfaqiR4CsNznPHg1on5e51G',
    b'\xf5s\x1d\xff\xec\xb9\xd1zG\rg\xd7\xa64lPO\xb4!\x824\xad:Q]m\x1d\xa4\xdd/\xe6{Hq\xc9(/\x9dv\xa6C\xa3\xc9\xb7\n\x18dZeI\xfat\xe2\xb6e\xb1\xbf\xdf\xae43\xdd\x91\x8d'
    'tz1gcLysnvTeJWhaM7zxQt3MACHFBmykLdLG',
    b"\xd9\x8a\xbdA\xf8r\x9e\xa2\xcc\x15\xcbB\x0flW\x89\xe6\naU#\xb61\xb5o\x8a\xa3 \x97,\x1c\xc9\xedA\xa5'\xdd\x90\xea:\x96\x80\x83\xec\xea\xa7\x88\x92\xae\x1es\xe1\x06N\x9f-\x8d\xfc\x808\xdb\x9fh\xa8"
    'tz1cmFTyaf6yp4ajCS1XJuWG5itSQxK9jrwJ',
    b'\x02DZ\xf3\xcd\x1c\xd8\x19\x92V8\xb5\xbd^^S{\xa2\xc2Q\x10\xec\x9e\x15:\xf4\xa5O\xf9\x82d\xf7\xc4\x7f\t\x86\x05\x8c\x00\xe4LQ\xfb\x15@\x95Fm\x1ad\x08\xe6?\xbbE9\x1f\xb9lZ\xc5w\x02a'
    '''

    if 'babylonnet' in instance.blockchain.endpoint:
        if instance.owner.is_company:
            instance.address = 'tz1grSQDByRpnVs7sPtaprNZRp531ZKz6Jmm'
            instance.crypted_key = encrypt(b'0\xbb4S\xaa\x86 <J\xf7\xbe\x05\xe9\xc3\xdbRi\xc7\x8a\xb2\xb1n\xd8:\xbd\xdb\x18\\*\xb7\x00\x94\x17\x14?b\xff\x9c/A\xb3\x0e\xe0\x0b\x8cd\xd23\xfd\xa4:\xdf\x05\xeb\x82\x9c\xfd.s>\xe9\xa8\xf4K')
        else:
            instance.address = 'tz1iqmduBYqk3sbHK35SP57DUc1U4SsrF416'
            instance.crypted_key = encrypt(b'\xd5\xa54\n\x8cxd*R=\x1b)\x10a\x1b\xf51\xbc\xef\xe3\xc8n\x06\xe3\xd4\xc9n\xb3\x06\x93{&\xd7\xbc^vH1\xf9\n\x07\xba\xf5&\xf8\x96\xe34,U\x18\xa1\xfa\x8apP\xd2F\xc1\xc2eR\x13%')
        return

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

    @property
    def provider(self):
        parts = self.provider_class.split('.')
        mod = importlib.import_module(
            '.'.join(parts[:-1])
        )
        return getattr(mod, parts[-1])(self)


def blockchain_hacks(sender, instance, **kwargs):
    if os.getenv('CI') and 'ethereum' in instance.provider_class:
        instance.endpoint = 'http://eth:8545'
signals.pre_save.connect(blockchain_hacks, sender=Blockchain)


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
        db_index=True,
        max_length=255,
        null=True,
        blank=True
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
        on_delete=models.CASCADE,
        related_name='call_set',
    )
    function = models.CharField(max_length=100, null=True)
    args = JSONField(null=True)
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
        if not self.hold and not self.txhash:
            self.txhash = self.deploy()

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
