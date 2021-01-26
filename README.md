djblockchain is a Django app which provides tables to store data about
blockchain transactions with a blockchain abstraction layer and a deployment
spooler workflow.

The Transaction table holds transaction data such as the contract name,
address, function to call if any, and arguments in a JSONField, so you don't
have to query the blockchain to display transaction informations to users.

When you create a Transaction in djblockchain, it's "state" will be "held" by
default. Nothing happens when the state is "held", but change it to "deploy"
and the spooler will find that there is a new Transaction to deploy on the
blockchain.

The spooler will then set the Transaction.state to "deploying" to indicate that
it is trying to deploy, and then call Transaction.deploy() which is in charge
of deploying the contract or calling a function. It will retry as long as you
want, to prevent failing just because of a network error or something. In case
of success, it will set the Transaction.state to "watch" and then spool itself
again to ensure any further modification will be done in its own database
transaction.

Note that djblockchain supports custom Transaction subclasses which translates
into new tables with a foreign key to the Transaction table, thanks to Django
Model Inheritance feature. This allows Equisafe to have a dedicated subclass
per contract type of method call type, and override the deploy method to add
custom logic when needed.

The spooler will find the Transaction with state="watch" and call
Transaction.watch() which will wait until enough blocks append on the
blockchain to reduce the risk of loosing the transaction. It waits 5 minutes by
default, in the case of an error it will return and the spooler will try to
watch this Transaction again later because it will still be in the "watch"
state, trying to move forward the state of the other Transactions that you may
have in the database. In the case of success, it will set the state to
"postdeploy", and return to ensure that nothing else causes a database
transaction abort.

The spooler will then find the Transaction with state="postdeploy", and if your
custom Transaction class has a postdeploy() method then it will set the state
to "postdeploying" and call that. This is were you can chain calls on the
blockchain, for example with NyX, the IssuingEntity Transaction class
represents an issuing entity contract which is used to create the KYCIssuer
contract. So, we have IssuingEntity.postdeploy() which creates a KYCIssuer
Transaction subclass that the spooler will find and try to deploy and so on.

Note that the deploy and watch implementation are Provider based, we currently
have 3 providers:

- Tezos
- Ethereum
- Fake

As such, it makes it easy to migrate from Ethereum to Tezos, and the Fake
provider is, well, a fake blockchain provider that fakes contract addresses in
the deploy() and watch() functions. This makes it easy to test/develop your
user interface without even involving the blockchain. Note that we also
maintain a Tezos sandbox which behaves like the Ethereum sandbox to make tests
easier.

As per requirements, there should only be one spooled job per transaction
sender at the time. The spooler will do several sender accounts in parallel,
but not treat several transactions of a same sender in parallel.

While nothing can prevent that in theory with uWSGI spooler, this is ensured by
the Account.spool method which retrieves the Caller responsible for this
Account sender_spool, and only spools it if it's not currently running. So, the
sender_queue job should only be spooled by the Account.spool() method.

This is tested by the test_concurrency, which creates two accounts and creates
3 transactions in parallel, the two first with the first user account and the
last one with the second user account.

It will then wait until all transactions are finished, and compare the state
history entries as such:

- the second transaction should not start prior to the first one finishing,
  because they are of the same sender account, avoiding nonce race conditions
- the third transaction should start in parallel with the first transaction,
  because they are of different sender accounts, so that one failing sender
  account does not block other sender accounts

Note that state_set will also add a new entry with the timestamp and the state
name in the new Transaction.history JSON list field. This is also logged with
the INFO level.

States recap:

- held: this transaction is only stored in the database
- deploy: this transaction should be deployed when possible
- deploying: this transaction is currently being deployed
- watch: this transaction has been deployed, it needs to be watched
- watching: this transaction is currently being watched
- postdeploy: this transaction has been watched and it needs to execute postdeploy
- postdeploying: this transaction's postdeploy method is currently being executed
- done: this transaction is finished

This is tested in the test_state, that runs a uWSGI server in a process fork
with a mini-project dedicated to testing djblockchain.djblockchain offers an easy fault-tolerant Django app to maintain a database of
contracts with blockchain synchronization.
