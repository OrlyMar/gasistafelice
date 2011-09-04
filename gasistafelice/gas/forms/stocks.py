from django import forms
from django.forms.formsets import formset_factory

from gasistafelice.lib.widgets import RelatedFieldWidgetCanAdd
from gasistafelice.lib.fields.forms import CurrencyField
from gasistafelice.lib.formsets import BaseFormSetWithRequest

from gasistafelice.base.const import ALWAYS_AVAILABLE
from gasistafelice.gas.models.base import GASSupplierStock
from gasistafelice.supplier.models import SupplierStock, Product

class GASSupplierStockForm(forms.Form):

    id = forms.IntegerField(required=True, widget=forms.HiddenInput)
    enabled = forms.BooleanField(required=False)

    def __init__(self, request, *args, **kw):
        super(GASSupplierStockForm, self).__init__(*args, **kw)
        self.__pact = request.resource.pact

    def save(self):
        gasstock = GASSupplierStock.objects.get(pk=self.cleaned_data['id'])
        gasstock.enabled = self.cleaned_data.get('enabled', False)
        gasstock.save()


GASSupplierStockFormSet = formset_factory(
                                form=GASSupplierStockForm, 
                                formset=BaseFormSetWithRequest, 
                                extra=0
                          )
