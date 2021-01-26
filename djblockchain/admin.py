from django.contrib import admin

from .models import (
    Account,
    Block,
    Blockchain,
    Transaction,
)


class AccountAdmin(admin.ModelAdmin):
    list_display = (
        'address',
        'blockchain',
        'owner',
    )
    list_filter = (
        'blockchain',
    )
    search_fields = (
        'owner__email',
        'address',
    )
    raw_id_fields = (
        'owner',
    )
    readonly_fields = ('balance',)

    def balance(self, obj):
        balance = None
        try:
            balance = obj.blockchain.provider.get_balance(
                obj.address,
                obj.private_key,
            )
            return balance
        except Exception as e:
            return None

admin.site.register(Account, AccountAdmin)
admin.site.register(Block)


class BlockchainAdmin(admin.ModelAdmin):
    list_display = (
        'is_active',
        'name',
        'endpoint',
    )
    list_filter = (
        'provider_class',
    )
    list_display_links = (
        'name',
    )
    list_editable = (
        'is_active',
    )


admin.site.register(Blockchain, BlockchainAdmin)


class TransactionAdmin(admin.ModelAdmin):
    def sender_name(self, obj):
        return obj.sender.owner if obj.sender_id else ""

    def receiver_name(self, obj):
        return obj.receiver.owner if obj.receiver_id else ""

    def no_error(self, obj):
        return not obj.error

    no_error.boolean = True

    list_display = (
        'id',
        'txhash',
        'sender_name',
        'sender',
        'receiver_name',
        'receiver',
        'blockchain',
        'contract_name',
        'function',
        'state',
        'no_error',
        'updated_at',
    )
    search_fields = (
        'id',
        'txhash',
        'sender__address',
        'sender__owner__name',
        'sender__owner__contact_name',
        'sender__owner__email',
        'sender__owner__contact_email',
    )
    list_filter = (
        'sender__blockchain',
        'state',
        'created_at',
        'updated_at',
        'state',
        'contract_name',
        'function',
    )
    ordering = ['-updated_at']
    raw_id_fields = (
        'sender',
        'receiver',
        'contract',
    )
    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'state',
        'sender',
        'receiver',
        'blockchain',
        'txhash',
        'block',
        'gasprice',
        'gas',
        'contract_address',
        'contract_name',
        'contract',
        'function',
        'args',
        'explorer_link',
    )


admin.site.register(Transaction, TransactionAdmin)
