import json
import os
import pytest
import time

from django.contrib.auth import get_user_model
from djtezos.models import Blockchain, Contract, Call, Transfer, Transaction


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


@pytest.mark.django_db
def test_story(user, tzlocal):
    account = user.account_set.create(blockchain=tzlocal)

    contract = Transaction.objects.create(
        sender=account,
        contract_micheline=mich,
        contract_name='test',
        args={'int': '1'},
        state='deploy',
    )
    contract = Contract.objects.get(pk=contract.pk)
    assert contract.state == 'done'

    call = Transaction.objects.create(
        sender=account,
        contract=contract,
        function='replace',
        args=[3],
        state='deploy',
    )
    call = Call.objects.get(pk=call.pk)
    assert call.state == 'done'

    balance = account.get_balance()
    account2 = user.account_set.create(blockchain=tzlocal)
    balance2 = account2.get_balance()
    transfer = Transaction.objects.create(
        sender=account,
        receiver=account2,
        amount=10000,
        state='deploy',
    )
    transfer = Transfer.objects.get(pk=transfer.pk)
    assert transfer.state == 'done'
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
def test_wrong_storage(user, tzlocal):
    account = user.account_set.create(blockchain=tzlocal)

    contract = Transaction.objects.create(
        sender=account,
        contract_micheline=mich,
        contract_name='test',
        args={'string': 'aoeu'},
        state='deploy',
    )
    contract = Contract.objects.get(pk=contract.pk)
    assert contract.state == 'deploy-aborted'
    assert contract.error


@pytest.mark.django_db
def test_wrong_args(user, tzlocal):
    account = user.account_set.create(blockchain=tzlocal)

    contract = Transaction.objects.create(
        sender=account,
        contract_micheline=mich,
        contract_name='test',
        args={'int': '1'},
        state='deploy',
    )
    contract = Contract.objects.get(pk=contract.pk)
    assert contract.state == 'done'

    call = Transaction.objects.create(
        sender=account,
        contract=contract,
        function='replace',
        args=['foobar'],
        state='deploy',
    )
    call = Call.objects.get(pk=call.pk)
    assert call.state == 'deploy-aborted'
    assert call.error
