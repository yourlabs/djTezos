import importlib
import json
import logging
import time
import os

from djcall.models import Caller
from django.conf import settings
from pytezos import Contract, Key, pytezos
from mnemonic import Mnemonic
from tenacity import retry, stop_after_attempt
from rest_framework.exceptions import ValidationError
from pytezos.rpc.node import RpcError

from .models import Account
from .provider import BaseProvider

logger = logging.getLogger('djblockchain.tezos')

SETTINGS = dict(TEZOS_CONTRACTS='')
SETTINGS.update(getattr(settings, 'DJBLOCKCHAIN', {}))


class Provider(BaseProvider):
    sandbox_ids = (
        'edsk3gUfUPyBSfrS9CCgmCiQsTCHGkviBDusMxDJstFtojtc1zcpsh',
        'edsk39qAm1fiMjgmPkw1EgQYkMzkJezLNewd7PLNHTkr6w9XA2zdfo',
        'edsk4ArLQgBTLWG5FJmnGnT689VKoqhXwmDPBuGx3z4cvwU9MmrPZZ',
        'edsk2uqQB9AY4FvioK2YMdfmyMrer5R8mGFyuaLLFfSRo8EoyNdht3',
        'edsk4QLrcijEffxV31gGdN2HU7UpyJjA8drFoNcmnB28n89YjPNRFm',
    )

    def create_wallet(self, passphrase):
        mnemonic = Mnemonic('english').generate(128)
        key = Key.from_mnemonic(mnemonic, passphrase, curve=b'ed')
        if self.blockchain.name == 'tzlocal':
            for sandbox_id in self.sandbox_ids:
                sandbox = pytezos.key.from_encoded_key(sandbox_id)
                existing = Account.objects.filter(
                    address=sandbox.public_key_hash()
                )
                key = sandbox
                if not existing:
                    break

            '''
            fucking tezos replies with empty rpc errors, disabling feature
            if not found:
                balances = dict()

                for sandbox_id in self.sandbox_ids:
                    sandbox = pytezos.key.from_encoded_key(sandbox_id)
                    client = pytezos.using(
                        key=sandbox,
                        shell=self.blockchain.endpoint,
                    )
                    balances[client.balance()] = client

                client = balances[max(balances)]
                opg = self.wait_injection(
                    client,
                    client.transaction(
                        amount=10000,
                        destination=key.public_key_hash()
                    ).autofill().sign().inject()
                )
            '''

        return key.public_key_hash(), key.secret_exponent

    def get_balance(self, account_address, private_key):
        client = self.get_client(private_key)
        balance = client.account()['balance']
        return balance

    def get_client(self, private_key):
        return pytezos.using(
            key=Key.from_secret_exponent(private_key),
            shell=self.blockchain.endpoint,
        )

    def get_contract_path(self, contract_name):
        return os.path.join(
            SETTINGS['TEZOS_CONTRACTS'],
            contract_name + '.json'
        )

    def wait_injection(self, client, operation):
        opg = None
        tries = 100
        while tries and not opg:
            try:
                opg = client.shell.blocks[-20:].find_operation(operation['hash'])
                if opg['contents'][0]['metadata']['operation_result']['status'] == 'applied':
                    logger.info(f'Revealed {sender}')
                    break
                else:
                    raise StopIteration()
            except StopIteration:
                opg = None
            tries -= 1
            time.sleep(1)
        return opg

    @retry(reraise=True, stop=stop_after_attempt(30))
    def deploy(self, sender, private_key, contract_name, *args):
        logger.debug(f'{contract_name}.deploy({args}): start')
        client = self.get_client(private_key)

        if not client.balance():
            raise ValidationError(f'{sender} needs more than 0 tezies')

        # key reveal dance
        try:
            operation = client.reveal().autofill().sign().inject()
        except RpcError as e:
            if 'previously_revealed_key' in e.args[0]['id']:
                pass
        else:
            logger.debug(f'Revealing {sender}')
            opg = self.wait_injection(client, operation)
            if not opg:
                raise ValidationError(f'Could not reveal {sender}')

        tx = dict(
            code=json.loads(
                open(
                    self.get_contract_path(contract_name)
                ).read()
            ),
            storage=args[0]
        )
        tx = client.origination(tx).autofill().sign()
        result = self.write_transaction(sender, private_key, tx)
        logger.info(f'{contract_name}.deploy({args}): {result}')
        return result

    def write_transaction(self, sender, private_key, tx):
        try:
            origination = tx.inject()
            return origination['hash']
        except RpcError as e:
            if 'Counter' in e.args[0]['msg']:
                logger.info(f'{tx.address} counter error')
            else:
                logger.info(f'{tx.address} other rpc error')
                raise
            i = 300
            origination = None
            while True:
                try:
                    logger.info(f"{tx.address} try #{300 - i + 1}")
                    origination = tx.inject()
                    if 'hash' in origination:
                        logger.info(f"{tx.address} HASH = " + str(origination['hash']))
                        break
                except:
                    if i:
                        time.sleep(1)
                        # tx.shell.wait_next_block()
                        i -= 1
                    else:
                        raise
            logger.info(f"{tx.address} RETURNING HASH = " + str(origination['hash']))
            return origination['hash']

    @retry(reraise=True, stop=stop_after_attempt(30))
    def send(self,
             sender,
             private_key,
             contract_name,
             contract_address,
             function_name,
             *args):
        logger.debug(f'{contract_name}.{function_name}({args}): start')
        client = self.get_client(private_key)
        logger.debug(f'{contract_name}.{function_name}({args}): counter = {client.account()["counter"]}')
        ci = client.contract(contract_address)
        method = getattr(ci, function_name)
        tx = method(*args)
        result = self.write_transaction(sender, private_key, tx)
        logger.debug(f'{contract_name}.{function_name}({args}): {result}')
        return result

    def watch(self, transaction, spool=True, postdeploy_kwargs=None):
        if spool:
            return Caller(
                callback='djblockchain.tezos.transaction_watch',
                kwargs=dict(
                    pk=transaction.pk,
                    module=type(transaction).__module__,
                    cls=type(transaction).__name__,
                    postdeploy_kwargs=postdeploy_kwargs,
                ),
            ).spool('blockchain')

        client = pytezos.using(shell=self.blockchain.endpoint)
        opg = None
        i = 300
        while True:
            try:
                opg = client.shell.blocks[
                      -(5 + int(self.blockchain.confirmation_blocks)):
                      ].find_operation(transaction.txhash)
                # client.shell.wait_next_block() (might be a better alternative to wait for blocks to append)
                # level_operation = opg['contents'][0]['level']  (not always present)

                # level of the chain latest block
                level_position = client.shell.head.metadata()['level']['level_position']
                operation_block_id = opg['branch']
                level_operation = client.shell.blocks[operation_block_id].level()
                if (level_position - level_operation >= self.blockchain.confirmation_blocks):
                    break
            except:
                if i:
                    time.sleep(1)
                    i -= 1
                else:
                    raise

        func = transaction.function or 'deploy'
        sign = (
            f'{transaction.contract_name}.{func}(*{transaction.args})'
        )
        logger.debug(f'{sign}: watch')
        transaction.gas = opg['contents'][0]['fee']
        result = opg['contents'][0]['metadata']['operation_result']
        if 'originated_contracts' in result:
            transaction.contract_address = result['originated_contracts'][0]
        transaction.accepted = True
        transaction.status = True
        transaction.save()
        logger.info(f'{sign}: success')
        logger.debug(f'{sign}.postdeploy(): start')
        transaction.refresh_from_db()
        transaction.postdeploy(**(postdeploy_kwargs or dict()))
        logger.info(f'{sign}.postdeploy(): success')


def transaction_watch(**kwargs):
    module = importlib.import_module(kwargs['module'])
    cls = getattr(module, kwargs['cls'])
    transaction = cls.objects.get(pk=kwargs['pk'])
    transaction.watch(
        spool=False,
        postdeploy_kwargs=kwargs.get('postdeploy_kwargs', dict())
    )
