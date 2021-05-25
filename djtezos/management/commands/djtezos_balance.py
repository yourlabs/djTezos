import requests

from pytezos import pytezos

from django.core.management.base import BaseCommand, CommandError

from djtezos.models import Account


class Command(BaseCommand):
    help = 'Synchronize balance'

    def handle(self, *args, **options):
        for account in Account.objects.all():
            data = requests.get(account.get_tzkt_api_url()).json()
            if 'balance' in data:
                newbalance = data['balance'] / 1_000_000
            else:
                newbalance = 0
            if account.balance != newbalance:
                print(f'Updating balance of {account} from {account.balance} to {newbalance}')
                account.balance = newbalance
                account.save()
