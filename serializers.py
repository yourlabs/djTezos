from rest_framework import serializers

from .models import (
    Account,
    Blockchain,
    Transaction,
)


class AccountSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Account
        fields = (
            'url',
            'address',
            'blockchain',
            'owner',
        )


class BlockchainSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Blockchain
        fields = (
            'name',
            'endpoint',
            'provider_class',
            'url',
        )


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = (
            'id',
            'url',
            'created_at',
            'updated_at',
            'txhash',
            'accepted',
            'status',
            'gasprice',
            'gas',
            'contract_address',
            'contract_name',
            'function',
            'args',
        )
