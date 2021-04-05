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
    TransactionCreateSerializer,
    TransactionUpdateSerializer,
)


class AccountViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset().filter(
            owner=self.request.user
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
    queryset = Blockchain.objects.filter(is_active=True)
    serializer_class = BlockchainSerializer
    permission_classes = [IsAuthenticated]


class TransactionViewSet(viewsets.ModelViewSet):
    queryset = Transaction.objects.all()
    permission_classes = [IsAuthenticated]
    search_fields = [
        'txhash',
        'contract_name',
        'contract_address',
        'blockchain__name',
        'sender__address',
        'receiver__address',
    ]

    def get_serializer_class(self):
        if self.action == 'create':
            return TransactionCreateSerializer
        if self.action in ('partial_update', 'update'):
            return TransactionUpdateSerializer
        return TransactionSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        if not self.request.user.is_superuser:
            qs = qs.for_user(self.request.user)

        return qs
