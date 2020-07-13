from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action

from django import http
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

    @action(detail=True, methods=['get'])  # noqa: C901
    def details(self, request, pk):
        try:
            account = self.get_queryset().get(pk=pk)
            balance = account.blockchain.provider.get_balance(
                account.address,
                account.private_key,
            )
            return http.JsonResponse({
                'balance': balance,
            })
        except Account.DoesNotExist:
            raise http.Http404

class BlockchainViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Blockchain.objects.all()
    serializer_class = BlockchainSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(is_active=True)


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()

        qs = qs.filter(
            Q(sender__owner=self.request.role.entity_represented)
            | Q(receiver__owner=self.request.role.entity_represented),
        )

        txhash = self.request.query_params.get('txhash', None)

        if txhash is not None:
            qs = qs.filter(txhash=txhash)

        if 'sender_only' in self.request.query_params:
            qs = qs.filter(sender__owner=self.request.role.entity_represented)

        return qs
