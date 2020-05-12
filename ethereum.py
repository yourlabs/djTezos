import importlib
import logging
import json
import os
import re
import time

from web3 import Web3
import web3.exceptions

from django.conf import settings
from rest_framework.exceptions import ValidationError
from tenacity import retry, stop_after_attempt, wait_fixed

from .models import Block
from .provider import BaseProvider


logger = logging.getLogger('djblockchain.ethereum')

SETTINGS = dict(ETHEREUM_CONTRACTS='')
SETTINGS.update(getattr(settings, 'DJBLOCKCHAIN', {}))


class Provider(BaseProvider):
    @property
    def client(self):
        return Web3(Web3.HTTPProvider(self.blockchain.endpoint))

    def create_wallet(self, passphrase):
        acct = self.client.eth.account.create(passphrase)
        return acct.address, acct.privateKey

    def get_balance(self, account_address, private_key):
        balance_wei = self.client.eth.getBalance(account_address)
        balance_ether = self.client.fromWei(balance_wei, 'ether')
        return balance_ether

    def get_contract_path(self, contract_name):
        return os.path.join(
            SETTINGS['ETHEREUM_CONTRACTS'],
            contract_name + '.json'
        )

    def get_contract_data(self, contract_name):
        with open(self.get_contract_path(contract_name), 'r') as f:
            return json.load(f)

    def send(self,
             sender,
             private_key,
             contract_name,
             contract_address,
             function_name,
             *args):

        logger.debug(f'{contract_name}.{function_name}({args}): start')

        data = self.get_contract_data(contract_name)
        Contract = self.client.eth.contract(  # noqa
            abi=data['abi'],
            address=contract_address,
        )
        funcs = Contract.find_functions_by_name(function_name)
        if not funcs:
            raise Exception(f'{function_name} not found in {contract_name}')

        func = funcs[0]

        args = list(args)


        for i, inp in enumerate(func.abi.get('inputs', [])):
            if inp['type'].startswith('bytes32'):
                args[i] = self.client.toBytes(hexstr=args[i])

        tx = func(*args)

        result = self.write_transaction(
            sender,
            private_key,
            tx,
        )

        logger.info(f'{contract_name}.{function_name}({args}): {result}')

        return result

    def deploy(self, sender, private_key, contract_name, *args):
        logger.debug(f'{contract_name}.deploy({args}): start')

        data = self.get_contract_data(contract_name)

        Contract = self.client.eth.contract(  # noqa
            abi=data['abi'],
            bytecode=data['bytecode']
        )

        tx = Contract.constructor(*args)
        result = self.write_transaction(sender, private_key, tx)
        logger.info(f'{contract_name}.deploy({args}): {result}')
        return result

    @retry(wait=wait_fixed(2), reraise=True, stop=stop_after_attempt(7))
    def write_transaction(self, sender, private_key, tx):
        nonce = self.client.eth.getTransactionCount(sender)
        options = {
            'from': sender,
            'nonce': nonce,
        }
        options['gas'] = self.client.eth.estimateGas(tx.buildTransaction(options))
        built = tx.buildTransaction(options)
        signed_txn = self.client.eth.account.sign_transaction(
            built,
            private_key=private_key
        )

        self.client.eth.sendRawTransaction(signed_txn.rawTransaction)
        return self.client.toHex(
            self.client.keccak(signed_txn.rawTransaction)
        )

    def watch(self, transaction):
        func = transaction.function or 'deploy'
        sign = (
            f'{transaction.contract_name}.{func}(*{transaction.args})'
        )
        logger.debug(f'{sign}: watch')
        receipt = self.client.eth.waitForTransactionReceipt(
            transaction.txhash,
            3600 * 24
        )

        block_number = self.client.eth.blockNumber
        receipt_block_number = receipt['blockNumber']

        while block_number - receipt_block_number < self.blockchain.confirmation_blocks:
            receipt = self.client.eth.waitForTransactionReceipt(
                transaction.txhash,
                3600 * 24
            )
            block_number = self.client.eth.blockNumber
            receipt_block_number = receipt['blockNumber']
            time.sleep(5)

        transaction.gas = receipt['gasUsed']
        transaction.block = Block.objects.get_or_create(
            blockchain=self.blockchain,
            number=receipt['blockNumber'],
        )[0]
        if receipt.contractAddress:
            transaction.contract_address = receipt.contractAddress

    def call(self, contract_name, contract_address, function, *args):
        # supported by ethereum only
        data = self.get_contract_data(contract_name)

        Contract = self.client.eth.contract(  # noqa
            abi=data['abi'],
            address=contract_address,
        )

        func = Contract.find_functions_by_name(function)[0]

        try:
            result = func(*args).call()
        except (
            web3.exceptions.BadFunctionCallOutput,
            web3.exceptions.BlockNotFound,
            web3.exceptions.BlockNumberOutofRange,
            web3.exceptions.CannotHandleRequest,
            web3.exceptions.FallbackNotFound,
            web3.exceptions.InfuraKeyNotFound,
            web3.exceptions.InsufficientData,
            web3.exceptions.InvalidAddress,
            web3.exceptions.InvalidEventABI,
            web3.exceptions.LogTopicError,
            web3.exceptions.ManifestValidationError,
            web3.exceptions.MismatchedABI,
            web3.exceptions.NameNotFound,
            web3.exceptions.NoABIEventsFound,
            web3.exceptions.NoABIFound,
            web3.exceptions.NoABIFunctionsFound,
            web3.exceptions.PMError,
            web3.exceptions.StaleBlockchain,
            web3.exceptions.TimeExhausted,
            web3.exceptions.TransactionNotFound,
            web3.exceptions.ValidationError,
        ) as e:
            # todo: handle other kinds of error
            # in one case whilst testing locally :
            #    e was "BadFunctionCallOutput('Could not transact with/call contract function,
            #    is contract deployed correctly and chain synced?')"
            msg = re.match(  # noqa
                ".*b'([\\\]x[0-9a-z]{2,3} ?)+(?P<msg>[^\\\]+)",  # noqa
                e.args[0]
            )
            if not msg:
                raise Exception(e.args[0])
            else:
                raise Exception(msg.group('msg'))
            # raise Exception(e.args[0])

        # value returned is either a single value
        if len(func.abi['outputs']) == 1:
            if func.abi['outputs'][0]['type'].startswith('bytes32'):
                return result.hex()
            return result

        # or an object
        # https://sft-protocol.readthedocs.io/en/latest/kyc.html#KYCBase.getInvestor
        output = {}
        for i, out in enumerate(func.abi['outputs']):
            if out['type'].startswith('bytes32'):
                output[out['name']] = result[i].hex()
            else:
                output[out['name']] = result[i]
        return output
