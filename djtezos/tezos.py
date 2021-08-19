import importlib
import json
import logging
import time
import os

from django.conf import settings
from pytezos import Contract, Key, pytezos
from mnemonic import Mnemonic
from tenacity import retry, stop_after_attempt
from django.core.exceptions import ValidationError
from pytezos.rpc.node import RpcError
from requests.exceptions import ConnectionError

from .exceptions import PermanentError, TemporaryError
from .models import Account, Transaction
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
            time.sleep(100 - tries)
        return opg

    def deploy(self, transaction):
        if transaction.amount:
            return self.transfer(transaction)
        elif transaction.function:
            return self.send(transaction)
        else:
            return self.originate(transaction)

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
            code=transaction.contract_micheline,
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
        transaction.gas = origination['contents'][0]['fee']
        transaction.txhash = origination['hash']

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

    def watch(self, transaction):
        logger.debug(f'{transaction}: watch begin')

        client = pytezos.using(shell=self.blockchain.endpoint)
        start_level = current_level = client.shell.head.metadata()['level']['level_position']
        max_depth = 50  # max number of blocks to search backwards for

        while True:
            # try to find the operation by iterating over ranges of 20 blocks
            current_level = 0 if current_level < 0 else current_level
            blocks = client.shell.blocks[current_level - 20:current_level]
            logger.debug(f'{transaction}: searching backward {current_level-20}:{current_level}')

            try:
                opg = blocks.find_operation(transaction.txhash)
                break
            except StopIteration:
                current_level -= 20

            if start_level - current_level >= max_depth:
                raise TemporaryError(f'Did not find operation {transaction.txhash}')

        level_operation = client.shell.blocks[opg['branch']].level()
        offset = client.shell.head.metadata()['level_info']['level_position'] - level_operation
        if self.blockchain.confirmation_blocks and offset < self.blockchain.confirmation_blocks:
            logger.info(f'{transaction} watch: not enough confirmation blocks')
            raise TemporaryError('Not enough confirmation blocks')

        result = opg['contents'][0]['metadata']['operation_result']
        transaction.gas = opg['contents'][0]['fee']
        if 'originated_contracts' in result:
            transaction.contract_address = result['originated_contracts'][0]

        logger.info(f'{transaction}: watch success')

    def watch_blockchain(self, blockchain):
        client = pytezos.using(shell=blockchain.endpoint)
        start_level = current_level = client.shell.head.metadata()['level_info']['level_position']

        if blockchain.max_level and start_level < blockchain.max_level:
            # reorg
            Transaction.objects.filter(
                sender__blockchain=blockchain,
                level__gte=blockchain.max_level,
            ).exclude(level=None).update(
                level=None,
                txhash=None,
                contract_address=None,
                state='held',
            )
            blockchain.max_level = blockchain.max_level
            blockchain.save()
            return  # commit to reorg in a transaction

        if blockchain.max_level and start_level == blockchain.max_level:
            # no need to go all way back further if we are up to date just
            # check the head
            max_depth = 1

        if blockchain.max_level and start_level > blockchain.max_level:
            # go all way back to where we left
            max_depth = (start_level - blockchain.max_level) or 1

        if not blockchain.max_level:
            # go with an arbitrary backlog
            max_depth = 500

        hashes = Transaction.objects.filter(
            sender__blockchain=blockchain
        ).exclude(
            txhash=None
        ).values_list('txhash', flat=True)

        contracts = Transaction.objects.exclude(
            contract_address=None,
        ).filter(
            sender__blockchain=blockchain,
            function=None,
            amount=None,
        )

        addresses = contracts.values_list(
            'contract_address',
            flat=True,
        )

        while current_level and start_level - current_level < max_depth:
            print('level', current_level)
            block = client.shell.blocks[current_level]
            for ops in block.operations():
                for op in ops:
                    if op['hash'] not in hashes:
                        continue
                    for content in op.get('contents', []):
                        if content['kind'] == 'origination':
                            print(f'Syncing origination from {op["hash"]}')
                            result = content['metadata']['operation_result']
                            tx = Transaction.objects.get(txhash=op['hash'])
                            spool = not tx.contract_address
                            tx.level = current_level
                            tx.contract_address = result['originated_contracts'][0]
                            tx.gas = content['fee']
                            tx.state_set('done')
                            tx.call_set.update(
                                contract_address=tx.contract_address,
                            )

                        elif content['kind'] == 'transaction':
                            print(f'Syncing transaction from {op["hash"]}')
                            destination = content.get('destination', None)
                            if destination in addresses:
                                self.sync_call(current_level, op, content, contracts, blockchain)

            current_level -= 1

        blockchain.max_level = start_level - 1  # consider head as suceptible to change
        blockchain.save()

    def sync_call(self, level, op, content, contracts, blockchain):
        contract = contracts.get(contract_address=content['destination'])

        parameters = content.get('parameters', {})

        call = contract.call_set.filter(
            txhash=op['hash'],
            contract_address=content['destination'],
        ).first()
        if not call:
            call = Call(
                txhash=op['hash'],
                function=parameters['entrypoint'],
                contract_address=content['destination'],
                contract=contract,
            )
        call.state = 'done'
        call.args_mich = parameters['value']
        call.gas = content['fee']
        call.level = level
        call.save()
