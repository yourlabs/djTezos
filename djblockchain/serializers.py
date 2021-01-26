from rest_framework import serializers

from .models import (
    Account,
    Blockchain,
    Transaction,
)




class BlockchainSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Blockchain
        fields = (
            'id',
            'url',
            'name',
            'endpoint',
            'provider_class',
            'explorer',
            'is_active',
            'description',
            'confirmation_blocks',
        )

class AccountSerializer(serializers.HyperlinkedModelSerializer):
    blockchain = BlockchainSerializer(required=False)

    class Meta:
        model = Account
        fields = (
            'url',
            'address',
            'blockchain',
            'owner',
        )


class TransactionSerializer(serializers.ModelSerializer):
    blockchain = BlockchainSerializer(required=False)
    class Meta:
        model = Transaction
        fields = (
            'id',
            'url',
            'created_at',
            'updated_at',
            'txhash',
            'state',
            'gasprice',
            'gas',
            'contract_address',
            'contract_name',
            'function',
            'args',
            'error',
            'blockchain',
        )
