import json
import os
import pytest
import time

from django.contrib.auth import get_user_model
from djtezos.models import Blockchain, Contract, Call, Transfer, Transaction
from djtezos.management.commands.djtezos_write import Command as Write
from djtezos.management.commands.djtezos_balance import Command as Balance


User = get_user_model()

os.environ['DJBLOCKCHAIN_MOCK'] = '1'


mich = [
  { "prim": "storage", "args": [ { "prim": "int" } ] },
  { "prim": "parameter", "args": [ { "prim": "or", "args": [ { "prim": "unit", "annots": [ "%double" ] }, { "prim": "int", "annots": [ "%replace" ] } ] } ] },
  {
    "prim": "code",
    "args": [
      [
        { "prim": "UNPAIR" },
        {
          "prim": "IF_LEFT",
          "args": [ [ { "prim": "DROP" }, { "prim": "PUSH", "args": [ { "prim": "int" }, { "int": "2" } ] }, { "prim": "MUL" } ], [ { "prim": "SWAP" }, { "prim": "DROP" } ] ]
        },
        { "prim": "NIL", "args": [ { "prim": "operation" } ] },
        { "prim": "PAIR" }
      ]
    ]
  }
]


@pytest.fixture
def user():
    return User.objects.create(username='test_models_story')


@pytest.fixture
def tzlocal():
    return Blockchain.objects.create(
        name='tzlocal',
        endpoint='http://tz:8732',
        provider_class='djtezos.tezos.Provider',
        is_active=True,
        confirmation_blocks=1,
    )


@pytest.fixture
def account(user, tzlocal):
    account = user.account_set.create(blockchain=tzlocal)
    account.generate_private_key()
    account.save()
    return account


def watch(tx, check):
    tries = 100
    while tries and not check(tx):
        tx.sender.blockchain.provider.watch_blockchain(tx.sender.blockchain)
        tx.refresh_from_db()
        tries -= 1
        time.sleep((100 - tries) / 2.0)
    assert check(tx)


def write():
    Balance().handle()
    Write().handle()


@pytest.mark.django_db
def test_story(user, account, tzlocal):
    contract = Transaction.objects.create(
        sender=account,
        contract_micheline=mich,
        contract_name='test',
        args={'int': '1'},
        state='deploy',
    )
    write()
    watch(contract, lambda tx: tx.state == 'done')

    call = Transaction.objects.create(
        sender=account,
        contract=contract,
        function='replace',
        args=[3],
        state='deploy',
    )
    write()
    watch(call, lambda tx: tx.state == 'done')

    balance = account.get_balance()
    account2 = user.account_set.create(blockchain=tzlocal)
    account2.generate_private_key()
    account2.save()
    balance2 = account2.get_balance()
    transfer = Transaction.objects.create(
        sender=account,
        receiver=account2,
        amount=10000,
        state='deploy',
    )
    write()
    watch(transfer, lambda tx: tx.state == 'done')

    tries = 30
    while tries and not account.get_balance() < balance:
        time.sleep(1)
        tries -= 1
    assert account.get_balance() < balance

    while tries and not account2.get_balance() > balance2:
        time.sleep(1)
        tries -= 1
    assert account2.get_balance() > balance2


@pytest.mark.django_db
def test_wrong_storage(account):
    contract = Transaction.objects.create(
        sender=account,
        contract_micheline=mich,
        contract_name='test',
        args={'string': 'aoeu'},
        state='deploy',
    )
    write()
    contract = Contract.objects.get(pk=contract.pk)
    assert contract.state == 'retrying'
    assert contract.error


@pytest.mark.django_db
def test_wrong_args(account):
    contract = Transaction.objects.create(
        sender=account,
        contract_micheline=mich,
        contract_name='test',
        args={'int': '1'},
        state='deploy',
    )
    write()
    contract.refresh_from_db()
    assert contract.state == 'watching'

    # need now to call the watch function that will first either:
    # - drop txhash and contract_address of all transactions of level above the
    #   current head, to support the reorg case, this will allow users to retry
    #   their transactions
    # - or synchro new operations from current head level to last synchronized
    #   level
    # - and then poll the head for new level to start synchronizing on it
    while not contract.contract_address:
        account.blockchain.provider.watch_blockchain(account.blockchain)
        contract.refresh_from_db()

    assert contract.state == 'done'

    call = Transaction.objects.create(
        sender=account,
        contract=contract,
        function='replace',
        args=['foobar'],
        state='deploy',
    )
    write()
    call = Call.objects.get(pk=call.pk)
    assert call.state == 'retrying'
    assert call.error
