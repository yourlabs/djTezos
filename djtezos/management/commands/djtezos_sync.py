import logging

from pytezos import pytezos

from django.core.management.base import BaseCommand, CommandError

from djtezos.models import Blockchain, Contract, Call, Transaction


logger = logging.getLogger('djtezos.djtezos_sync')


class Command(BaseCommand):
    help = 'Synchronize external transactions'

    def handle(self, *args, **options):
        for blockchain in Blockchain.objects.filter(is_active=True):
            try:
                blockchain.provider.watch_blockchain(blockchain)
            except Exception as exception:
                logger.exception(exception)
