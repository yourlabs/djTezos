from pytezos import pytezos

from django.core.management.base import BaseCommand, CommandError

from djtezos.models import Blockchain, Contract, Call, Transaction


class Command(BaseCommand):
    help = 'Synchronize external transactions'

    def handle(self, *args, **options):
        for blockchain in Blockchain.objects.filter(is_active=True):
            blockchain.provider.watch_blockchain(blockchain)
