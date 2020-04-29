from uuid import uuid4
import importlib
import json
import logging
import random
import time
import os

from djcall.models import Caller
from django.conf import settings
from pytezos import Contract, Key, pytezos
from tenacity import retry, stop_after_attempt
from rest_framework.exceptions import ValidationError
from pytezos.rpc.node import RpcError

from .models import Account
from .provider import BaseProvider

logger = logging.getLogger('djblockchain.tezos')


SLEEP = int(os.getenv('FAKEBC_SLEEP', '0'))


class Provider(BaseProvider):
    def create_wallet(self, passphrase):
        return '0x4cf2425EF2D798D17e2ecB37' + str(random.randint(
            1000000000000000, 9999999999999999
        )), b'_\xf2\x7f\xf6\xfd\xadu:\n\xe3Y\xc3a\xd2\x92\x97o3F\x86\xf5[\x9d\x10\x9d{S\x87zh\xde\xc1'

        '''
    def get_client(self, private_key):
        return None
        '''

    def get_balance(self, account_address, private_key):
        return 1234

    def deploy(self, sender, private_key, contract_name, *args):
        return uuid4()

    @retry(reraise=True, stop=stop_after_attempt(30))
    def send(self,
             sender,
             private_key,
             contract_name,
             contract_address,
             function_name,
             *args):
        time.sleep(SLEEP)
        return uuid4()

    def watch(self, transaction, spool=True, postdeploy_kwargs=None):
        time.sleep(SLEEP)
        transaction.contract_address = '0x123123123123123123123123' + str(random.randint(
            1000000000000000, 9999999999999999
        ))
        transaction.accepted = True
        transaction.status = True
        transaction.gas = 1
        transaction.save()
        transaction.refresh_from_db()
        transaction.postdeploy(**(postdeploy_kwargs or dict()))
