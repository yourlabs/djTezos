import asyncio
from datetime import datetime
import os
import pytest
import httpx
import shlex
import signal
import shutil
import subprocess
import tempfile
import textwrap
import time

from django.apps import apps
from django.conf import settings

User = apps.get_model(settings.AUTH_USER_MODEL)

from .models import Account, Blockchain, Transaction


# 2 is a setting that works on a laptop, increase it on CI servers
FAKEBC_SLEEP = int(os.getenv('FAKEBC_SLEEP', '2'))


@pytest.fixture
def bc():
    return Blockchain.objects.get_or_create(
        provider_class='djblockchain.fake.Provider',
    )[0]


@pytest.fixture
def acc(bc):
    return User.objects.create().account_set.filter(blockchain=bc).first()


@pytest.mark.django_db
def test_caller(acc):
    tx1 = Transaction.objects.create(sender=acc, state='held')
    tx2 = Transaction.objects.create(sender=acc, state='done')
    assert tx1.sender.caller == tx2.sender.caller


@pytest.mark.django_db
def test_to_spool(acc, monkeypatch):
    for state in ('held', 'done'):
        Transaction.objects.bulk_create([Transaction(sender=acc, state=state)])

    i = 1
    for state in ('deploy', 'postdeploy', 'watch'):
        Transaction.objects.bulk_create([Transaction(sender=acc, state=state)])
        assert acc.to_spool.count() == i
        i += 1


@pytest.mark.django_db
def test_fsm_start_finish(acc):
    for state in ('held', 'done'):
        # these states do not move
        tx = Transaction.objects.create(sender=acc, state=state)
        tx.refresh_from_db()
        assert tx.state == state


@pytest.fixture(scope="module")
def uwsgi():
    uwsgi = subprocess.check_output(['which', 'uwsgi']).decode('utf8').strip()
    child = os.fork()
    spooler = tempfile.mkdtemp() + '/blockchain'
    os.makedirs(spooler)
    if not child:
        env = dict(FAKEBC_SLEEP=str(FAKEBC_SLEEP))
        for key, value in os.environ.items():
            if key.startswith('POSTGRES_'):
                env[key] = value
        # child process replaces with uwsgi process
        plugins = []
        plugins_path = '/usr/lib/uwsgi/plugins'
        if not os.path.exists(plugins_path):
            plugins_path = '/usr/lib/uwsgi'
        files = os.listdir(plugins_path)
        if 'python3_plugin.so' in files:
            plugins.append('python3')
        else:
            plugins.append('python')
        if 'http_plugin.so' in files:
            plugins.append('http')

        os.execvpe(
            uwsgi,
            [
                'uwsgi',
                '--spooler=' + spooler,
                '--spooler-processes=2',
                '--spooler-frequency=0',
                '--spooler-chdir=' + os.getcwd(),
                '--http-socket=localhost:7999',
                '--plugins=' + ','.join(plugins),
                '--module=djblockchain.demo:application',
            ],
            env,
        )
    tries = 100
    while tries:
        try:
            httpx.get('http://localhost:7999/tx/')
        except:
            tries -= 1
        else:
            break
    yield spooler, 'localhost:7999'
    os.kill(child, signal.SIGKILL)
    shutil.rmtree(spooler)


async def user(name):
    async with httpx.AsyncClient() as client:
        user = await client.post('http://localhost:7999/user/', data=dict(
            username=datetime.now().strftime('%s') + name, password='foo',
        ))
        assert user.status_code == 201, user.content
        user = user.json()
        user['accounts'] = dict()

        accounts = await client.get('http://localhost:7999/account/')
        assert accounts.status_code == 200, accounts.content
        for account in accounts.json():
            if account['owner'] != user['url']:
                continue
            bc = await client.get(account['blockchain'])
            assert bc.status_code == 200, bc.content
            bc = bc.json()
            user['accounts'][bc['name']] = account
        return user


async def tx(user, bc='fake'):
    async with httpx.AsyncClient() as client:
        tx = await client.post('http://localhost:7999/transaction/', data=dict(
            sender=user['accounts'][bc]['url'],
            state='deploy',
            contract_name='test',
        ))
        assert tx.status_code == 201, tx.content
        return tx.json()


@pytest.mark.uwsgi
@pytest.mark.asyncio
async def test_state(uwsgi):
    """
    This tests that we can get the state of the transaction in real-time.

    Despite that a transaction mutates from a state to another in the same
    function: this basically tests that the state is correctly updated by
    different transactions in real time.
    """
    testuser = await user('testuser')
    testtx = await tx(testuser)
    assert testtx['state'] == 'deploy'

    # the transaction will roll from deploy to postdeploylet's make sure that
    # we can get the intermediary states before the done state
    tries = FAKEBC_SLEEP * 5
    got_deploy = got_watch = False
    while tries:
        result = httpx.get(testtx['url'])
        assert result.status_code == 200
        testtx = result.json()
        if testtx['state'] == 'deploying':
            got_deploy = True
        elif testtx['state'] == 'watching':
            assert got_deploy, 'Got to the watch state early'
            got_watch = True
        elif testtx['state'] == 'done':
            assert got_watch, 'Got to the done state early'
            break
        tries -= 1
        time.sleep(1)

    assert tries, 'Transaction did not go through states in time'


def txget():
    result = httpx.get('http://localhost:7999/transaction/')
    assert result.status_code == 200
    return result.json()


def txclean():
    # clean all transactions
    for transaction in txget():
        httpx.delete(transaction['url'])
    assert not len(txget())


def txwait():
    # wait until all transactions are finished
    tries = FAKEBC_SLEEP * 15
    while tries:
        notfinished = False
        for transaction in txget():
            if transaction['state'] != 'done':
                notfinished = True
                continue
        if not notfinished:
            break
        tries -= 1
        time.sleep(1)

    assert tries, 'Transaction should have been done by now' + str(txget())


async def txhist(*tx):
    async with httpx.AsyncClient() as client:
        tx = await asyncio.gather(*[client.get(t['url']) for t in tx])

    return [dict(t.json()['history']) for t in tx]


@pytest.mark.uwsgi
@pytest.mark.asyncio
async def test_concurrency(uwsgi):
    """
    Test that transactions of the same sender wait for each other, and that
    transactions from different senders are executed in parallel.

    This test asserts of the efficiency of the whole spooler.
    """
    txclean()

    foo, bar = await asyncio.gather(user('foo'), user('bar'))

    # second transaction has same account as first, should execute after first,
    # but last transaction should execute asap, because it has a different
    # sender account
    tx1, tx3 = await asyncio.gather(tx(foo), tx(bar))
    tx2 = await tx(foo)

    txwait()

    tx1, tx2, tx3 = await txhist(tx1, tx2, tx3)

    print('tx1', tx1)
    print('tx2', tx2)
    print('tx3', tx3)

    # deployment of bar's transaction should not have waited for deployment of
    # foo's transaction: different senders, run in parallel
    assert tx1['done'] > tx3['deploying']

    # the second tx of foo should not have started before its first tx has
    # started: they must not run in parallel
    assert tx2['deploying'] >= tx1['done']


@pytest.mark.uwsgi
@pytest.mark.asyncio
async def test_failure(uwsgi):
    txclean()

    john, doe = await asyncio.gather(user('john'), user('doe'))

    # second transaction has same account as first, should execute after first,
    # but last transaction should execute asap, because it has a different
    # sender account
    tx1, tx3 = await asyncio.gather(
        tx(john, 'faildeploy'),
        tx(doe),
    )
    tx2 = await tx(john, 'faildeploy')

    time.sleep(FAKEBC_SLEEP * 4)

    # tx1 should be in a failing loop
    assert httpx.get(tx1['url']).json()['error']
    assert httpx.get(tx1['url']).json()['state'] == 'deploying'
    # tx2 should not have been able to start
    assert httpx.get(tx2['url']).json()['state'] == 'deploy'

    tx1, tx2, tx3 = await txhist(tx1, tx2, tx3)

    assert 'watching' not in tx1    # deploy should be failing
    assert not tx2                  # not started: blocked by tx1
    assert 'postdeploy' in tx3      # started anyway: different account
