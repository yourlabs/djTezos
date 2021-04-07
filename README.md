# djTezos: Django-Tezos

Django-Tezos provides Django Models and uWSGI Spooler (djCall) integration with
PyTezos.

## Install djTezos

Install djtezos with pip then add djtezos to INSTALLED_APPS.

Run ./manage.py migrate to create tables for djtezos models.

You need a SECRET_KEY that is sufficiently long for AES.

## Add Blockchains

Blockchain is the first model you have to manage, you can do it in the admin.
For any blockchain, you can choose a Python Provider Class, such as
``djtezos.tezos.Provider`` or ``djtezos.fake.Provider`` for a mock that you can
use in tests.

Example:

```py
tzlocal = Blockchain.objects.create(
    name='tzlocal',
    endpoint='http://tz:8732',
    provider_class='djtezos.tezos.Provider',
    is_active=True,
    confirmation_blocks=1,
)
```

Run tzlocal with: `docker run --rm --publish 8732:8732 yourlabs/tezos`

Add to /etc/hosts: `tz` on line starting with 127.0.0.1

In gitlab-ci, add:

```yaml
services:
- name: yourlabs/tezos
  alias: tz
```

## Create accounts

Create an account for a user:

```py
account = user.account_set.create(blockchain=tzlocal)
```

Users can have as many accounts as you want.

## Queue

Transactions are queued in the database with the Transaction model. You can
emit 3 types of Transactions.

### Deploy a smart contract

Create a Transaction with a contract_code to deploy a smart contract:

```python
    contract = Transaction.objects.create(
        sender=account,
        contract_code=mich,
        contract_name='test',
        args={'int': '1'},
        state='deploy',
    )
```

You may then retreive it through either of the Transaction model and the
Contract proxy model.

### Call a smart contract function

Call a smart contract function with a new Transaction:

```py
    call = Transaction.objects.create(
        sender=account,
        contract=contract,
        function='replace',
        args=[3],
        state='deploy',
    )
```

This calls the replace function with only one arg: an integer of 3.

A Call proxy model is also available to retrieve.

### Execute a transfer

Create a transfer on the blockchain:

```py
    transfer = Transaction.objects.create(
        sender=account,
        receiver=account2,
        amount=10000,
        state='deploy',
    )
```
