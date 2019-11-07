from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from django.db.models import Q

from .models import (
    Account,
    Blockchain,
    Transaction,
)


from .serializers import (
    AccountSerializer,
    BlockchainSerializer,
    TransactionSerializer,
)


class AccountViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset().filter(
            owner=self.request.role.entity_represented
        )


class BlockchainViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Blockchain.objects.all()
    serializer_class = BlockchainSerializer
    permission_classes = [IsAuthenticated]


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()

        qs.filter(
            Q(sender__owner=self.request.role.entity_represented)
            | Q(receiver__owner=self.request.role.entity_represented),
        )

        txhash = self.request.query_params.get('txhash', None)

        if txhash is not None:
            qs = qs.filter(txhash=txhash)

        return qs
