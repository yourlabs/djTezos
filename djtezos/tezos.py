import importlib
import json
import logging
import time
import os

from django.conf import settings
from pytezos import Contract, Key, pytezos
from mnemonic import Mnemonic
from tenacity import retry, stop_after_attempt
from rest_framework.exceptions import ValidationError
from pytezos.rpc.node import RpcError
from requests.exceptions import ConnectionError

from .exceptions import PermanentError, TemporaryError
from .models import Account
from .provider import BaseProvider

logger = logging.getLogger('djtezos.tezos')

SETTINGS = dict(TEZOS_CONTRACTS='')
SETTINGS.update(getattr(settings, 'DJBLOCKCHAIN', {}))


RETRIES = 3


class Bank:
    address = 'tz1Tc5WeytFSQvciXAX7xb7SeUBwZ2q4dWXj'
    key = b'B\xfeNx\r\xd4\x90\xb7c\x07\x0c\x8a\xe4\r\x8d?\xfa\x137\xee\xe2$\xa9A)\xd7?\xf1\xfb\x9c\xb31\xa3\xd5J\xaf\xab\x84\xd0\x91IN\xc5\xdd\x1c\xd5\xb1\xcb@\x0c\xa3\xf6E\xb3\x15(^/\x8aw\xee\xf6h\xf2'  # noqa


class Provider(BaseProvider):
    sandbox_ids = (
        'edsk3gUfUPyBSfrS9CCgmCiQsTCHGkviBDusMxDJstFtojtc1zcpsh',
        'edsk39qAm1fiMjgmPkw1EgQYkMzkJezLNewd7PLNHTkr6w9XA2zdfo',
        'edsk4ArLQgBTLWG5FJmnGnT689VKoqhXwmDPBuGx3z4cvwU9MmrPZZ',
        'edsk2uqQB9AY4FvioK2YMdfmyMrer5R8mGFyuaLLFfSRo8EoyNdht3',
        'edsk4QLrcijEffxV31gGdN2HU7UpyJjA8drFoNcmnB28n89YjPNRFm',
    )

    @retry(reraise=True, stop=stop_after_attempt(RETRIES))
    def transfer(self, transaction):
        """
        rpc error if balance too low :
        RpcError ({'amount': '120000000000000000',
              'balance': '3998464237867',
              'contract': 'tz1gjaF81ZRRvdzjobyfVNsAeSC6PScjfQwN',
              'id': 'proto.006-PsCARTHA.contract.balance_too_low',
              'kind': 'temporary'},)
        """
        logger.debug(f'Transfering {transaction.amount} from {transaction.sender} to {transaction.receiver}')
        client = self.get_client(
            transaction.sender.private_key,
            reveal=True,
            sender=transaction.sender.address
        )
        tx = client.transaction(
            destination=transaction.receiver.address,
            amount=transaction.amount,
        ).autofill().sign()
        result = self.write_transaction(tx, transaction)
        return result

    def get_sandbox_account(self):
        key = None
        for sandbox_id in self.sandbox_ids:
            sandbox = pytezos.key.from_encoded_key(sandbox_id)
            existing = Account.objects.filter(
                address=sandbox.public_key_hash()
            )
            key = sandbox
            if not existing:
                return key
        return key

    def get_richest_sandbox_account(self):
        balances = dict()
        for sandbox_id in self.sandbox_ids:
            sandbox = pytezos.key.from_encoded_key(sandbox_id)
            sandbox_balance = self.get_balance(sandbox.public_key_hash(), sandbox.secret_exponent)
            balances[sandbox_balance] = sandbox

        max_tezies = max(balances)
        return balances[max_tezies]


    def create_wallet(self, passphrase):
        mnemonic = Mnemonic('english').generate(128)
        key = Key.from_mnemonic(mnemonic, passphrase, curve=b'ed')
        if self.blockchain.name == 'tzlocal':
            # during tests, use sandbox accounts to avoid having to make time-eating transfers
            if 'DJBLOCKCHAIN_MOCK' in os.environ and os.environ['DJBLOCKCHAIN_MOCK']:
                key = self.get_sandbox_account()
        return key.public_key_hash(), key.secret_exponent

    def _provision_tzlocal(self, address):
        if 'DJBLOCKCHAIN_MOCK' in os.environ and os.environ['DJBLOCKCHAIN_MOCK']:
            pass
        # pick the sandbox account with the most tezies and transfer to the new account
        DEFAULT_TZLOCAL_TEZIES = 1_200_000_000
        try:
            richest_sandbox = self.get_richest_sandbox_account()
            self.transfer(
                richest_sandbox.public_key_hash(),
                richest_sandbox.secret_exponent,
                address,
                DEFAULT_TZLOCAL_TEZIES
            )
        except ConnectionError as e:
            logger.info(f"Connection error while trying to either get balance or transfer tezies to {address}")

    def _provision_carthagenet(self, address):
        bank = self.get_client(Bank.key)
        balance = bank.account()['balance'] or 0
        if int(balance) < 50:
            logger.error(
                '[cartage] Insufficient balance to transfer',
                balance,
                Bank.address,
            )
        else:
            self.transfer(
                Bank.address,
                Bank.key,
                address,
                49_000_000,
            )
            logger.info(
                f'[cartage] {Bank.address} sent 49tz remains: {balance}')

    def provision(self, address):
        if self.blockchain.name == 'tezos carthagenet':
            self._provision_carthagenet(address)
        elif self.blockchain.name == 'tzlocal':
            self._provision_tzlocal(address)

    def get_balance(self, account_address, private_key):
        client = self.get_client(private_key)
        balance = client.account()['balance']
        return int(balance)

    def get_client(self, private_key, reveal=False, sender=None):
        client = pytezos.using(
            key=Key.from_secret_exponent(private_key),
            shell=self.blockchain.endpoint,
        )
        if reveal:
            # key reveal dance
            try:
                operation = client.reveal().autofill().sign().inject()
            except RpcError as e:
                if 'id' in e.args[0] and 'previously_revealed_key' in e.args[0]['id']:
                    return client
                raise e
            else:
                logger.debug(f'Revealing {sender}')
                opg = self.wait_injection(client, operation)
                if not opg:
                    raise ValidationError(f'Could not reveal {sender}')

        return client

    def wait_injection(self, client, operation):
        opg = None
        tries = 100
        while tries and not opg:
            try:
                opg = client.shell.blocks[-20:].find_operation(operation['hash'])
                if opg['contents'][0]['metadata']['operation_result']['status'] == 'applied':
                    logger.info(f'Revealed {client.key.public_key_hash()}')
                    break
                else:
                    raise StopIteration()
            except StopIteration:
                opg = None
            tries -= 1
            time.sleep(1)
        return opg

    @retry(reraise=True, stop=stop_after_attempt(RETRIES))
    def deploy(self, transaction):
        try:
            if transaction.amount:
                return self.transfer(transaction)
            elif transaction.function:
                return self.send(transaction)
            else:
                return self.originate(transaction)
        except RpcError as rpc_error:
            if rpc_error.args[0]['kind'] == 'temporary':
                raise TemporaryError(*rpc_error.args)
            elif rpc_error.args[0]['kind'] == 'permanent':
                raise PermanentError(*rpc_error.args)
            raise


    def originate(self, transaction):
        logger.debug(f'{transaction}.originate({transaction.args}): start')
        client = self.get_client(
            transaction.sender.private_key,
            reveal=True,
            sender=transaction.sender.address
        )

        if not client.balance():
            raise ValidationError(
                f'{transaction.sender.address} needs more than 0 tezies')

        tx = client.origination(dict(
            code=transaction.contract_code_python,
            storage=transaction.args,
        )).autofill().sign()

        result = self.write_transaction(tx, transaction)

        logger.info(f'{transaction.contract_name}.deploy({transaction.args}): {result}')
        return result

    def write_transaction(self, tx, transaction):
        origination = tx.inject(
            _async=False,
            # this seems not to be working for us, systematic TimeoutError
            #min_confirmations=transaction.blockchain.confirmation_blocks,
        )
        return origination['hash']

    @retry(reraise=True, stop=stop_after_attempt(RETRIES))
    def send(self, transaction):
        logger.debug(f'{transaction}({transaction.args}): get_client')
        client = self.get_client(transaction.sender.private_key)
        logger.debug(f'{transaction}({transaction.args}): counter = {client.account()["counter"]}')
        ci = client.contract(transaction.contract_address)
        method = getattr(ci, transaction.function)
        try:
            tx = method(*transaction.args)
        except ValueError as e:
            raise PermanentError(*e.args)
        result = self.write_transaction(tx, transaction)
        logger.debug(f'{transaction}({transaction.args}): {result}')
        return result

    def find_in_past_blocks(self, client, transaction):
        # find operation in a greater range of past blocks
        # we get a RPC error when executing .find_operation() on a range of length > 20
        # here is client.shell.blocks documentation :

        # Lists known heads of the blockchain sorted with decreasing fitness.
        # Optional arguments allows to returns the list of predecessors for known heads
        # or the list of predecessors for a given list of blocks.
        # :param length: The requested number of predecessors to returns (per requested head).
        # :param head: An empty argument requests blocks from the current heads.
        # A non empty list allow to request specific fragment of the chain.
        # :param min_date: When `min_date` is provided, heads with a timestamp before `min_date` are filtered out
        # :return: list[list[str]]
        #
        # []
        # Construct block query or get a block range.
        # :param block_id: Block identity or block range
        # int: Block level or offset from the head if negative;
        # str: Block hash (base58) or special names (head, genesis), expressions like `head~1` etc;
        # slice [:]: First value (start) must be int, second (stop) can be any Block ID or empty.
        # :return: BlockQuery or BlockSliceQuery

        BLOCK_DEPTH = 500
        level = client.shell.head.level() - int(self.blockchain.confirmation_blocks)
        min_level = max(level - BLOCK_DEPTH, 0)
        while level >= min_level:
            try:
                opg = client.shell.blocks[max(level - 20, 0):level].find_operation(transaction.txhash)
                return opg
            except StopIteration:
                level -= 20
                if level < min_level:
                    raise StopIteration
        raise StopIteration

    def watch(self, transaction):
        logger.debug(f'{transaction}: watch begin')

        client = pytezos.using(shell=self.blockchain.endpoint)
        current_level = client.shell.head.metadata()['level']['level_position']

        while True:
            # try to find the operation by iterating over ranges of 20 blocks
            current_level = 0 if current_level < 0 else current_level
            blocks = client.shell.blocks[current_level - 20:current_level]

            try:
                opg = blocks.find_operation(transaction.txhash)
                break
            except StopIteration:
                current_level -= 20

            if current_level == 0:
                raise PermanentError(f'Did not find operation {transaction.txhash}')

        level_operation = client.shell.blocks[opg['branch']].level()
        offset = client.shell.head.metadata()['level']['level_position'] - level_operation
        if offset < self.blockchain.confirmation_blocks:
            logger.info(f'{transaction} watch: not enough confirmation blocks')
            raise TemporaryError('Not enough confirmation blocks')

        result = opg['contents'][0]['metadata']['operation_result']
        transaction.gas = opg['contents'][0]['fee']
        if 'originated_contracts' in result:
            transaction.contract_address = result['originated_contracts'][0]

        logger.info(f'{transaction}: watch success')
