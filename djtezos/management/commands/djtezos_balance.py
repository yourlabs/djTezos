import decimal
import logging
import requests

from django.core.management.base import BaseCommand, CommandError

from djtezos.models import Account


logger = logging.getLogger('djtezos.balance')


class Command(BaseCommand):
    help = 'Synchronize balance'

    def handle(self, *args, **options):
        accounts = Account.objects.select_related('blockchain')
        for account in accounts:
            self.handle_account(account)

    def handle_account(self, account):
        from pytezos import pytezos
        try:
            client = pytezos.using(account.blockchain.endpoint)
            data = pytezos.account(account.address)
        except Exception as exception:
            logger.exception(exception)
            return

        try:
            balance = int(data['balance'])
        except Exception as exception:
            logger.exception(exception)
            balance = 0
        else:
            balance = decimal.Decimal(balance / 1_000_000)

        if account.balance != balance:
            print(f'Updating balance of {account} from {account.balance} to {balance}')
            account.balance = balance
            account.save()
