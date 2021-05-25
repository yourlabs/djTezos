from crudlfap import shortcuts as crudlfap
from crudlfap import html

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Account, Blockchain, Transaction


class AccountCreateView(crudlfap.CreateView):
    fields = [
        'name',
        'blockchain',
    ]

    def get_form(self):
        self.form = super().get_form()
        self.form.fields['blockchain'].queryset = Blockchain.objects.filter(is_active=True)
        return self.form

    def form_valid(self):
        self.form.instance.owner = self.request.user
        self.form.instance.generate_private_key()
        return super().form_valid()


class AccountRouter(crudlfap.Router):
    model = Account
    icon = 'vpn_key'
    views = [
        AccountCreateView,
        crudlfap.DeleteObjectsView,
        crudlfap.DetailView,
        crudlfap.DeleteView,
        crudlfap.ListView.clone(
            table_sequence=(
                'id',
                'address',
                'balance',
                'blockchain',
                'created_at',
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
    views = [
        crudlfap.CreateView,
        crudlfap.DeleteView,
        crudlfap.UpdateView,
        crudlfap.DetailView,
        crudlfap.ListView.clone(
            table_fields=('name', 'endpoint', 'is_active'),
        ),
    ]

    def has_perm(self, view):
        if view.urlname in ('list', 'detail'):
            return True
        return view.request.user.is_superuser or view.request.user.is_staff

    def get_queryset(self, view):
        return Blockchain.objects.all()
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
        return super().get_queryset(view).for_user(view.request.user).order_by('-created_at')


class TransactionRouter(TransactionRouterMixin, crudlfap.Router):
    model = Transaction
    icon = 'compare_arrows'
    views = [
        crudlfap.DeleteObjectsView,
        crudlfap.DetailView,
        crudlfap.DeleteView,
        crudlfap.ListView.clone(
            table_sequence=(
                'state',
                'contract_name',
                'txhash',
            ),
        ),
    ]
TransactionRouter().register()
