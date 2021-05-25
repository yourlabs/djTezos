import logging
import random
import time
import os

from .models import Transaction
from .provider import BaseProvider

logger = logging.getLogger('djtezos.tezos')


SLEEP = float(os.getenv('FAKEBC_SLEEP', '0.1'))


def fakehash(leet):
    return f'0x{leet}5EF2D798D17e2ecB37' + str(random.randint(
        1000000000000000, 9999999999999999
    ))


class Provider(BaseProvider):
    def create_wallet(self, passphrase):
        return (
            fakehash('w41137'),
            b'_\xf2\x7f\xf6\xfd\xadu:\n\xe3Y\xc3a\xd2\x92\x97o3F\x86\xf5[\x9d\x10\x9d{S\x87zh\xde\xc1'  # noqa
        )

    def get_balance(self, account_address, private_key):
        return 1234

    def transfer(self, transaction):
        time.sleep(SLEEP)
        return fakehash('d3pl0y3d7xh4sH')

    def send(self, transaction):
        time.sleep(SLEEP)
        return fakehash('d3pl0y3d7xh4sH')

    def deploy(self, transaction):
        time.sleep(SLEEP)
        return fakehash('d3pl0y3d7xh4sH')

    def watch(self, transaction):
        time.sleep(SLEEP)
        if not transaction.contract_address:
            transaction.contract_address = fakehash('c0n7r4c7')
        transaction.gas = 1337

    def watch_blockchain(self, blockchain):
        Transaction.objects.filter(sender__blockchain=blockchain).update(state='done')


class FailDeploy(Provider):
    def deploy(self, transaction):
        time.sleep(SLEEP)
        raise Exception('Deploy failed as requested')


class FailWatch(Provider):
    def watch(self, transaction):
        time.sleep(SLEEP)
        raise Exception('Watch failed as requested')
