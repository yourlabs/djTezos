# djTezos: Django-Tezos

Django-Tezos allows you to build webdApps - dApps enhanced with a web backend.
Django provides the web framework that is nice to work with, djtezos provides:

- blockchain indexer
- blockchain writer
- private key vault
- multiple blockchain support (with new provider class implementations)

In addition to these features, djtezos differenciates itself from dipdup
because it is expandable: it's just a module you add to your Django project, in
which you can add models, endpoints, and have an admin interface for free.

## Install djTezos

Install djtezos with pip then add djtezos to INSTALLED_APPS.

Run ./manage.py migrate to create tables for djtezos models.

You need a SECRET_KEY that is sufficiently long to be used for AES.

## Demo project

You may also use the example project:

- clone the repo
- in the repo, run `./manage.py migrate`
- then, run `./manage.py createsuperuser`
- then, run `./manage.py runserver`
- then, connect to http://localhost:8000/admin
- you will be able to follow this tutorial.

## Add Blockchains

Blockchain is the first model you have to manage, because nothing will happen
if you don't create a Blockchain object in your database.

For any blockchain, you need choose a Python Provider Class, such as
``djtezos.tezos.Provider`` or ``djtezos.fake.Provider`` for a mock that you can
use in tests.

### Sandbox example

Example with a local:

```py
tzlocal = Blockchain.objects.create(
    name='tzlocal',
    endpoint='http://tz:8732',
    provider_class='djtezos.tezos.Provider',
    is_active=True,
    confirmation_blocks=1,
)
```

Run tzlocal with: `docker run --name tz --rm --publish 8732:8732 yourlabs/tezos`

Add to /etc/hosts: `tz` on line starting with 127.0.0.1

In gitlab-ci, add:

```yaml
services:
- name: yourlabs/tezos
  alias: tz
```

### Mainnet example

Open http://localhost:8000/admin/djtezos/blockchain/add/ and save a Blockchain
with:

-

## Indexer

For the indexer to watch a contract for new calls, you need to insert the
contract in your database.

One easy way to find a contract is to go on
https://better-call.dev/stats/mainnet/fa2 and find a contract that has calls
and is as recent as possible, so that indexation doesn't take too long.

, you can do it in the admin on
http://localhost:8000/admin/djtezos/contract/add/ and set:

, ie.:

```py
from djtezos.models import Contract

Contract.objects.create(
)
```

The indexer is a script that runs and exit. You can have it running
continuously with a shell loop ie.:

```
sh -c 'while true; do ./manage.py djtezos_sync; sleep 60; done'
```

This will call the `blockchain.provider.watch_blockchain()` method for each
blockchain object in the database that has `is_active=True`.

## Create accounts

Create an account for a user:

```py
account = user.account_set.create(blockchain=tzlocal)
account.generate_private_key()
account.save()
```

Users can have as many accounts as you want.

## Queue

Transactions are queued in the database with the Transaction model. You can
emit 3 types of Transactions.

### Deploy a smart contract

Create a Transaction with a contract_micheline to deploy a smart contract:

```python
    contract = Transaction.objects.create(
        sender=account,
        name='TICKR',
        contract_micheline=mich,
        contract_name='PyMich FA 1.2',
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

## Migrate from v0.4.x

Callbacks have been rewritten in a release candidate version, where you need to:

- call `Account.generate_private_key()` **and** `Account.save()` to
  be able to deploy with it, or provision the private key by yourself
  through the AES encryption defined in models.py
- run at repeated intervals: `./manage.py djtezos_sync`, will catch up backlog
  at first, then sync incrementally, support reorg
- run at repeated intervals: `./manage.py djtezos_balance`

Also, you can't use a form to show a sender field without filling it.

## Migrate from djblockchain

1. change all your imports
2. remove migration dependencies to djblockchain to djtezos.0001_initial
3. execute the following SQL in production

```sql
alter table djblockchain_account rename to djtezos_account;
alter table djblockchain_blockchain rename to djtezos_blockchain;
alter table djblockchain_transaction rename to djtezos_transaction;
alter table djtezos_transaction drop column block_id;
drop table djblockchain_block;
alter table djtezos_transaction add column contract_micheline json null;
alter table djtezos_transaction add column amount int null;
insert into django_migrations (app, name, applied) values ('djtezos', '0001_initial', now());
update djtezos_blockchain set provider_class = replace(provider_class, 'djblockchain', 'djtezos');
```

Then, you might still have Blockchain objects with Ethereum provider, this has
not bee ported from djblockchain, you may deactivate them by setting
is_active=False or you can delete them but that will cascade delete of all
their transactions which might not be what existing users expect to happen on
your platform...
