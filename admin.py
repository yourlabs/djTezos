from django.contrib import admin

from .models import (
    Account,
    Block,
    Blockchain,
    Transaction,
)


admin.site.register(Account)
admin.site.register(Block)
admin.site.register(Blockchain)
admin.site.register(Transaction)
