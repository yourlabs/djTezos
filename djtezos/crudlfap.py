from crudlfap import shortcuts as crudlfap

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Account, Blockchain, Transaction


class AccountCreateView(crudlfap.CreateView):
    fields = [
        'blockchain',
    ]

    def form_valid(self):
        self.form.instance.owner = self.request.user
        return super().form_valid()


class AccountRouter(crudlfap.Router):
    model = Account
    icon = 'vpn_key'
    views = [
        AccountCreateView,
        crudlfap.DetailView,
        crudlfap.ListView.clone(
            table_sequence=(
                'address',
                'blockchain',
            ),
        ),
    ]

    def has_perm(self, view):
        return view.request.user.is_authenticated

    def get_queryset(self, view):
        return view.request.user.account_set.all()
AccountRouter().register()


class BlockchainRouter(crudlfap.Router):
    model = Blockchain
    icon = 'link'
BlockchainRouter().register()


class TransactionCreateView(crudlfap.CreateView):
    fields = (
        'state',
        'contract_name',
        'function',
        'args',
    )

    def get_form(self):
        super().get_form()
        self.form.fields['state'].choices = (
            ('held', _('Held')),
            ('deploy', _('To deploy')),
        )


class TransactionCreateView(crudlfap.CreateView):
    class form_class(forms.ModelForm):
        #contract = forms.ModelChoiceField(queryset=Contract.objects.none())

        class Meta:
            model = Transaction
            fields = (
                'sender',
                'function',
                'args',
            )

    def get_form(self):
        super().get_form()
        #self.form.fields['contract'].queryset = Code.objects.filter(
        #    owner=self.request.user)
        self.form.fields['sender'].queryset = Account.objects.filter(
            owner=self.request.user)


class TransactionRouterMixin:
    def has_perm(self, view):
        return view.request.user.is_authenticated

    def get_queryset(self, view):
        return super().get_queryset(view).for_user(view.request.user)


class TransactionRouter(TransactionRouterMixin, crudlfap.Router):
    model = Transaction
    icon = 'compare_arrows'
    views = [
        #TransactionCreateView,
        crudlfap.DeleteObjectsView,
        crudlfap.DeleteView,
        crudlfap.DetailView,
        crudlfap.ListView.clone(
            table_sequence=(
                'state',
                'contract_name',
                'txhash',
            ),
        ),
    ]
TransactionRouter().register()
