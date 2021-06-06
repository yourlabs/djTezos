from pytezos import pytezos

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from djtezos.models import Blockchain, Contract, Call, Transfer


class Command(BaseCommand):
    help = 'Synchronize external transactions'
    exclude_states = ('held', 'aborted', 'import', 'importing', 'done')

    def contracts(self):
        return Contract.objects.filter(
            contract_address=None,
            txhash=None,
        ).exclude(
            Q(sender__balance__in=(0, None))
            | Q(state__in=self.exclude_states)
        )

    def calls(self):
        return Call.objects.filter(
            txhash=None,
        ).exclude(
            Q(sender__balance__in=(0, None))
            | Q(state__in=self.exclude_states)
            | Q(contract_micheline__in=(None, ''))
            | Q(contract_address__in=(None, ''))
        )

    def transfers(self):
        return Transfer.objects.filter(
            txhash=None,
        ).exclude(
            Q(sender__balance__in=(0, None))
            | Q(state__in=self.exclude_states)
        )

    def handle(self, *args, **options):
        # is there any new transfer to deploy from an account with balance?
        transfer = self.transfers().filter(last_fail=None).first()
        if transfer:
            print(f'Deploying transfer {transfer}')
            return self.deploy(transfer)

        # is there any new contract to deploy from an account with balance?
        contract = self.contracts().filter(last_fail=None).first()

        if contract:
            print(f'Deploying contract {contract}')
            return self.deploy(contract)

        # is there any new contract call ready to deploy?
        call = self.calls().filter(last_fail=None).first()
        if call:
            print(f'Calling function {call}')
            return self.deploy(call)

        # is there any transfer to retry from an account with balance?
        transfer = self.transfers().order_by('last_fail').first()
        if transfer:
            print(f'Retrying transfer {transfer}')
            return self.deploy(transfer)

        contract = self.contracts().order_by('last_fail').first()

        if contract:
            print(f'Retrying contract {contract}')
            return self.deploy(contract)

        call = self.calls().order_by('last_fail').first()
        if call:
            print(f'Retrying function {call}')
            return self.deploy(call)


    def deploy(self, tx):
        tx.state_set('deploying')
        try:
            tx.provider.deploy(tx)
        except Exception as exception:
            tx.last_fail = timezone.now()
            tx.error = str(exception)

            deploys_since_last_start = 0
            for logentry in reversed(tx.history):
                if logentry[1] == 'deploying':
                    deploys_since_last_start += 1
                elif logentry[1] == 'aborted':
                    break
            if deploys_since_last_start >= 10:
                message = 'Aborting because >= 10 failures,'
                tx.error = ' '.join([
                    message,
                    'last error:',
                    tx.error,
                ])
                tx.state_set('aborted')
            else:
                tx.state_set('retrying')
        else:
            tx.last_fail = None
            tx.error = ''
            if tx.function or tx.amount:
                tx.state_set('done')
            else:
                tx.state_set('watching')
