from django import forms
from django.utils.translation import ugettext, ugettext_lazy as _

from gasistafelice.gas.models import ( GAS, GASSupplierOrder,
            GASMemberOrder, GASSupplierOrder, GASSupplierSolidalPact,
            GASSupplierOrderProduct, GASMemberOrder,
            Delivery, Withdrawal)

from gasistafelice.supplier.models import Supplier
from gasistafelice.base.models import Place, Person

from django.db import transaction
from django.db.models import Max
from django.forms.formsets import formset_factory
from django.forms import widgets
from django.contrib.admin import widgets as admin_widgets
from django.core.exceptions import ValidationError, PermissionDenied

from gasistafelice.lib.formsets import BaseFormSetWithRequest
from flexi_auth.models import ParamRole, PrincipalParamRoleRelation

from gasistafelice.base import const
from gasistafelice.exceptions import DatabaseInconsistent
from gasistafelice.utils import datetime_round_ten_minutes

from django.conf import settings

import copy
from datetime import timedelta, datetime, date

import logging

log = logging.getLogger(__name__)

FREQUENCY = [ 
    ('7', _('week')), 
    ('14', _('two weeks')), 
    ('21', _('three weeks')), 
    ('28', _('monthly')), 
    ('56', _('two months')), 
    ('84', _('three months')), 
    ('168', _('half year')), 
    ('336', _('year'))
]

def now_round_ten_minutes():

    dt = datetime.now()
    return datetime_round_ten_minutes(dt)

def get_day_from_choice(choice):
    day_num = 0
    if choice == 'MONDAY':
        day_num = 0
    elif choice == 'TUESDAY':
        day_num = 1
    elif choice == 'WEDNESDAY':
        day_num = 2
    elif choice == 'THURSDAY':
        day_num = 3
    elif choice == 'FRIDAY':
        day_num = 4
    elif choice == 'SATURDAY':
        day_num = 5
    elif choice == 'SUNDAY':
        day_num = 6
    return day_num

def first_day_on_or_after(daynum, dt):
    days_to_go = daynum - dt.weekday()
    if days_to_go:
        dt += timedelta(days_to_go)
    return dt

class BaseOrderForm(forms.ModelForm):

    #log.debug("BaseOrderForm")
    datetime_start = forms.SplitDateTimeField(label=_('Date start'), required=True, 
        help_text=_("when the order will be opened"), 
        widget=SplitDateTimeFormatAwareWidget, initial=now_round_ten_minutes
    )

    datetime_end = forms.SplitDateTimeField(label=_('Date end'), required=False, 
        help_text=_("when the order will be closed"), 
        widget=SplitDateTimeFormatAwareWidget
    )

    delivery_datetime = forms.SplitDateTimeField(required=False, 
        label=_('Delivery on/at'), widget=SplitDateTimeFormatAwareWidget
    )

    referrer_person = forms.ModelChoiceField(label=_('referrer'), 
        queryset=Person.objects.none(), required=True, 
        error_messages={'required': _(u'You must select one referrer (or create it in GAS details if empty)')}
    )

    def __init__(self, request, *args, **kw):
        #Strip request arg
        super(BaseOrderForm, self).__init__(*args, **kw)
        #gas_queryset = request.resource.gas.supplier_referrers_people
        referrers = request.resource.supplier_referrers_people
        #Ko: not rendered the form and the relative warning
#        if not referrers.count():
#            raise PermissionDenied(_("You cannot open an order without referrers"))

        self.fields['referrer_person'].queryset = referrers
        if self.fields.get('withdrawal_referrer_person'):
            self.fields['withdrawal_referrer_person'].queryset = referrers

    def clean(self):

        cleaned_data = self.cleaned_data
        dt_start = cleaned_data.get("datetime_start")
        dt_end = cleaned_data.get("datetime_end")
        dt_close = cleaned_data.get("delivery_datetime")
        #log.debug("AddOrderForm compare date [%s<%s<%s]" % (dt_start, dt_end, dt_close))
        # Only do something if both fields are valid so far.
        if dt_start and dt_end:
            if dt_start >= dt_end:
                 raise forms.ValidationError("some problem with date start and close date [%s<%s]" % (dt_start, dt_end))

        if dt_end and dt_close:
            if dt_end > dt_close:
                 raise forms.ValidationError("some problem with close and delivery date [%s<%s]" % (dt_end, dt_close))

        # Always return the full collection of cleaned data.
        return cleaned_data


    def get_appointment_instance(self, name, klass):

        ddt = self.cleaned_data['%s_datetime' % name]
        if self.cleaned_data.get('%s_city' % name):
            dc =self.cleaned_data['%s_city' % name]
            dp = self.cleaned_data['%s_addr_or_place' % name]

            try:
                p = Place.objects.get(city=dc, name__icontains=dp)
            except Place.DoesNotExist:
                try:
                    p = Place.objects.get(city=dc, address__icontains=dp)
                except Place.DoesNotExist:
                    p = Place(city=dc, name=dp)
                    p.save()
        else:
            if self.cleaned_data.get('pact'):
                pact = self.cleaned_data['pact']
                if not pact:
                    return None
                p = getattr(pact.gas.config, "%s_place" % name)
            else:
                return None

        d, created = klass.objects.get_or_create(date=ddt, place=p)
        #FIXME: get() returned more than one Delivery -- it returned 2! Lookup parameters were {'date': ..., 'place': <Place: ...>}
        return d

    def get_delivery(self):
        return self.get_appointment_instance('delivery', Delivery)

    def get_withdrawal(self):
        return self.get_appointment_instance('withdrawal', Withdrawal)

#-------------------------------------------------------------------------------

def GetNewOrder(obj, other_pact):
    #new_obj = obj
    #new_obj.id = None
    new_obj = GASSupplierOrder()
    if other_pact:
        new_obj.pact = other_pact
    else:
        new_obj.pact = obj.pact

    #planification
    new_obj.root_plan = obj  #.pk
    new_obj.datetime_start = obj.datetime_start
    new_obj.datetime_end = obj.datetime_end
    if other_pact:
        log.debug("TODO GetNewOrder how to create withdrawal? %s " % other_pact)
    else:
        if obj.withdrawal:
            new_obj.withdrawal = Withdrawal.objects.create(
                    date=obj.withdrawal.date,
                    place=obj.withdrawal.place
            )
    if obj.order_minimum_amount:
        new_obj.order_minimum_amount = obj.order_minimum_amount
    if obj.delivery_cost:
        new_obj.delivery_cost = obj.delivery_cost
    if other_pact:
        #retrieve the first referrer_person
        refs = other_pact.referrers_people
        if refs and refs.count()>0:
            new_obj.referrer_person = refs[0]
        else:
            refs = other_pact.supplier_referrers_people
            if refs and refs.count()>0:
                new_obj.referrer_person = refs[0]
            else:
                #FIXME: 'NoneType' object has no attribute 'user'. Cannot be real. But model permitted
                #Cannot create the order.
                log.debug("FIXME GetNewOrder retrieve almost one referrer_person for a specific pact?")
                #FIXME: for test only
                #return None
                new_obj.referrer_person = obj.referrer_person
        new_obj.delivery_referrer_person = new_obj.referrer_person
        new_obj.withdrawal_referrer_person = new_obj.referrer_person

        #Delivery retrieve a Place. The GAS place if older orders does not exist.
        if obj.delivery:
            #TODO: look for the last order in order to retrieve the last delivery Place
            #new_obj.delivery, created = Delivery.objects.get_or_create(
            #                date=obj.delivery.date,
            #                place=other_pact.gas.headquarter
            #        )
            new_obj.delivery = get_delivery(obj.delivery.date, other_pact.gas.headquarter)

    else:
        if obj.referrer_person:
            new_obj.referrer_person = obj.referrer_person
        if obj.delivery_referrer_person:
            new_obj.delivery_referrer_person = obj.delivery_referrer_person
        if obj.withdrawal_referrer_person:
            new_obj.withdrawal_referrer_person = obj.withdrawal_referrer_person
    if obj.group_id:
        new_obj.group_id = obj.group_id
    elif other_pact:
        log.debug("GetNewOrder cannot create other intergas order without a father group_id")
        return None
    return new_obj

def get_group_id():
    _group_id = 1
    _maxs = GASSupplierOrder.objects.all().aggregate(Max('group_id'))
    log.debug("get_group_id %s " % _maxs)
    if _maxs:
        # get the maximum attribute from the first record and add 1 to it
        _group_id = _maxs['group_id__max']
        if _group_id:
            _group_id += 1
        else:
            _group_id = 1
    return _group_id

def get_delivery(date, place):
    try:
        obj, created = Delivery.objects.get_or_create(
                date=date,
                place=place
        )
        return obj
    except Exception,e:
        log.debug("get_delivery: %s " % (e))
        objs = Delivery.objects.filter(date=date, place=place)
        if objs and objs.count()>0:
            return objs[objs.count()-1]
        else:
            log.debug("get_delivery cannot retrieve for place: %s and date: %s" % (place, date))
            return None


class AddOrderForm(BaseOrderForm):
    """ use in forms:
            DES             ChooseSupplier  ChooseGAS ChooseReferrer
            GAS             ChooseSupplier  OneGAS    ChooseReferrer
            Supplier        OneSupplier     ChooseGAS ChooseReferrer
            Solidal Pact    OneSupplier     OneGAS    ChooseReferrer
    """
    pact = forms.ModelChoiceField(label=_('pact'), 
        queryset=GASSupplierSolidalPact.objects.none(), 
        required=True, 
        error_messages={'required': _(u'You must select one pact (or create it in your GAS details if empty)')}
    )
    email_gas = forms.BooleanField(label=_('Send email to the LIST of the GAS?'), required=False)
    repeat_order = forms.BooleanField(label=_('Repeat this order several times?'), required=False)
    repeat_frequency = forms.ChoiceField(required=False, choices=FREQUENCY)
    repeat_until_date = forms.DateField(initial=date.now(), widget=admin_widgets.AdminDateWidget)

#WAS: INTERGAS 0

    def __init__(self, request, *args, **kw):

        #log.debug("AddOrderForm")
        super(AddOrderForm, self).__init__(request, *args, **kw)

        # SOLIDAL PACT
        #pacts = request.resource.pacts
        pacts = GASSupplierSolidalPact.objects.none()
        resource_pacts = request.resource.pacts
        # Limit pact to the logger user. Do not see pacts from other GAS than mine. 
        # Due to "Supplier" resources that was showing pact for another GAS.
        # user_pacts = request.user.person.pacts
        user_pacts = request.user.person.pacts.values_list('pk')
        #KO by fero: not needed "if resource_pacts and user_pacts and "
        if resource_pacts.count() and user_pacts.count():
            pacts = resource_pacts.filter(pk__in = user_pacts)
#       if not pacts.count():
#            raise PermissionDenied(_("You cannot open an order on a resource with no pacts"))
        #if pacts.count() == pacts.filter(gas=pacts[0].gas):

        if pacts.count() > 0:

            one_pact = pacts[0]
            self.fields['pact'].queryset = pacts
            self.fields['pact'].initial = one_pact

#WAS: INTERGAS 1

            # Person is the current user: referrers
            if request.user.person in self.fields['referrer_person'].queryset:
                self.fields['referrer_person'].initial = request.user.person
            elif self.fields['referrer_person'].queryset.count() > 0:
                self.fields['referrer_person'].initial = self.fields['referrer_person'].queryset[0]

            # If we are managing some pacts (even 1) of the same GAS,
            # we can set some additional defaults

            gas = pacts[0].gas

            #Next week by default
            dt = datetime.now()+timedelta(days=7)
            dt = first_day_on_or_after(6, dt)

            #Close
            d_c = get_day_from_choice(gas.config.default_close_day)
            if gas.config.default_close_day:
                dt = first_day_on_or_after(d_c, dt)
            if gas.config.default_close_time:
                dt = dt.replace(hour=gas.config.default_close_time.hour, minute=gas.config.default_close_time.minute)
            self.fields['datetime_end'].initial = dt

            #Delivery
            d_d = get_day_from_choice(gas.config.default_delivery_day)
            if d_d <= d_c:
                dt = dt+timedelta(days=7)
            if gas.config.default_delivery_day:
                dt = first_day_on_or_after(d_d, dt)
            if gas.config.default_delivery_time:
                dt = dt.replace(
                    hour=gas.config.default_delivery_time.hour, 
                    minute=gas.config.default_delivery_time.minute
                )
            self.fields['delivery_datetime'].initial = dt
            #log.debug("AddOrderForm delivery %s --> %s" % (d, dt))

    @transaction.commit_on_success
    def save(self, *args, **kwargs):
        self.instance.pact = self.cleaned_data['pact']
        _gas = self.instance.pact.gas

        #TODO: Control il delivery referrer is a GAS's referrer

        if self.cleaned_data.get('delivery_datetime'):
            d = self.get_delivery()
            self.instance.delivery = d

        if _gas.config.use_withdrawal_place:
            if self.cleaned_data.get('withdrawal_datetime'):
                w = self.get_withdrawal()
                self.instance.withdrawal = w

        log.debug("AddOrderForm CREATED pre_save")
        _created_order = super(AddOrderForm, self).save(*args, **kwargs)
        if self.instance:

#            #send email
#            #COMMENT domthu: Only if opened?  Util? use another politica
#            _send_email = self.cleaned_data['email_gas']
#            if bool(_send_email):
#                TODO: May be we only need to disable the notification if not enabled

#WAS: INTERGAS 2

            #Planification
            _repeat_order = self.cleaned_data['repeat_order']
            if bool(_repeat_order):
                _repeat_amount = int(self.cleaned_data['repeat_frequency'])
                _repeat_items = None
                _repeat_until_date = self.cleaned_data['repeat_until_date']
                #Calcul _repeat_items
                tmp_date = self.instance.datetime_end.date()
                log.debug("repeat params: start %s end %s(%s), until: %s desired: %s" % (
                    self.instance.datetime_start,
                    self.instance.datetime_end,
                    tmp_date,
                    _repeat_until_date,
                    _repeat_amount)
                )
                if _repeat_until_date and tmp_date and _repeat_until_date > tmp_date:
                    tmp_date = self.instance.datetime_start.date()
                    tmp_days = (_repeat_until_date - tmp_date).days
                    log.debug("repeat tmp date: %s days: %s" % (tmp_date, tmp_days))
                    _repeat_items = tmp_days // _repeat_amount
                log.debug("repeat parameters: %s, items: %s" % (_repeat_amount, _repeat_items))

                #verify params request is consistent
                if not _repeat_amount or not _repeat_items or _repeat_items < 1:
                    log.debug("repeat some parameter wrong")
                    return _created_order

                #Delete - Clean all previous planification
                previous_planed_orders = GASSupplierOrder.objects.filter(
                    pact=self.instance.pact,
                    datetime_start__gt = self.instance.datetime_start
                )
                log.debug("repeat previous_planed_orders: %s" % (previous_planed_orders))
                for order in previous_planed_orders:

                    #delete only prepared orders
                    if order.is_prepared or order.is_active:

#WAS: INTERGAS 3

                        log.debug("AddOrderForm repeat delete previous_planed_orders: %s" % (order))
                        order.delete()

                #Planificate new orders
                for num in range(1,_repeat_items+1):  #to iterate between 1 to _repeat_items
                    #program order
                    x_obj = GetNewOrder(self.instance, None)
                    r_q = (_repeat_amount*num)
                    r_dd = self.instance.delivery.date

                    #set date for open, close and delivery order
                    x_obj.datetime_start += timedelta(days=+r_q)
                    x_obj.datetime_end += timedelta(days=+r_q)
                    r_dd += timedelta(days=+r_q)

                    x_obj.delivery = get_delivery(r_dd, self.instance.delivery.place)

#WAS: INTERGAS 4

                    #create order
                    #COMMENT domthu: Don't understand why .save() not return true?
                    #WAS: if x_obj.save():
                    x_obj.save()
                    if x_obj.pk:
                        log.debug("repeat created order: %s " % (x_obj))

#WAS: INTERGAS 5

                    else:
                        log.debug("repeat NOT created: item %s, r_q %s, start %s , end %s , delivery %s" % (num, r_q, x_obj.datetime_start, x_obj.datetime_end, x_obj.delivery.date))
        return _created_order


    class Meta:
        model = GASSupplierOrder
        fields = ['pact', 'datetime_start', 'datetime_end', 'referrer_person']

        gf_fieldsets = [(None, {
            'fields' : ['pact'
                            , ('datetime_start', 'datetime_end')
                            , 'delivery_datetime'
                            , 'referrer_person'
                            , ('repeat_order', 'repeat_frequency', 'repeat_until_date')
            ]
        })]
#WAS: INTERGAS 6
#                            , 'email_gas'


#WAS: INTERGAS 0
#    intergas = forms.BooleanField(label=_('This order is InterGAS?'), required=False)
#    intergas_grd = forms.MultipleChoiceField(label=_('gas'), choices=GAS.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
#WAS: INTERGAS 1
#            gas_list = None
#            if pacts.count() == 1:
#                #log.debug("AddOrderForm only one pact %s" % pacts)
#                gas_list = [(gas.pk, gas.name) for gas in one_pact.supplier.gas_list]
#            else:
#                gas_list = [(gas.pk, gas.name) for gas in GAS.objects.all()]
#            self.fields['intergas_grd'].choices = gas_list
#WAS: INTERGAS 2
#        #InterGAS
#        _intergas_pacts = None
#        _intergas_number = None
#        _intergas = self.cleaned_data['intergas']
#        if bool(_intergas):

#            #interGAS gas list
#            _intergas_gas_list = self.cleaned_data['intergas_grd']
#            if _intergas_gas_list and _intergas_gas_list.count > 0:
#                #Add the default order's gas in the list
#                _intergas_pacts = set() #GAS.objects.none()
#                #_intergas_pacts.add(self.instance.pact)
#                for g in _intergas_gas_list:
#                    if int(g) != self.instance.gas.pk:
#                        log.debug("AddOrderForm intergas find %s another PACT:%s" % (g, self.instance.gas.pk))
#                        #_intergas_gas = _intergas_gas | GAS.objects.get(pk=g)
#                        x_g = GAS.objects.get(pk=g)
#                        if x_g:
#                            #retrieve the existing pact for this gas for this supplier. If exist.
#                            x_p = GASSupplierSolidalPact.objects.filter(gas=x_g, supplier=self.instance.pact.supplier)
#                            if x_p and x_p.count()>0:
#                                _intergas_pacts.add(x_p[0])
#                                if x_p.count() > 1:
#                                    log.debug("AddOrderForm intergas INCONGRUITY looking for gas %s and supplier %s" % (x_g, self.instance.pact.supplier))
#                #if _intergas_pacts.count() == 1:
#                if len(_intergas_pacts) == 0:
#                    #Not valid InterGAS almost 2 GAS to be an interGAS's order
#                    _intergas_pacts = None
#                else:
#                    #interGAS aggregation number
#                    _intergas_number = get_group_id()
#                    log.debug("AddOrderForm intergas --> (%s) another PACTs:%s" % (_intergas_number, _intergas_pacts))

#                    #Set instance as InterGAS
#                    self.instance.group_id = _intergas_number
#            #WAS: _intergas_orders = GASSupplierOrder.objects.none()
#            _intergas_orders = set()
#            if _intergas_pacts and _intergas_number:
#                log.debug("AddOrderForm interGAS OPEN for other GAS")
#                #Repeat this order for the overs GAS
#                for other_pact in _intergas_pacts:
#                    other_order = GetNewOrder(self.instance, other_pact)
#                    if other_order:
#                        #COMMENT domthu: Don't understand why .save() not return true?
#                        #WAS: if other_order.save():
#                        other_order.save()
#                        if other_order.pk:
#                            log.debug("repeat created another order: %s " % (other_order))
#                            _intergas_orders.add(other_order)
#                        else:
#                            log.debug("repeat another NOT created: pact %s, start %s , end %s , delivery %s" % (other_order.pact, other_order.datetime_start, other_order.datetime_end, other_order.delivery.date))
#WAS: INTERGAS 3
#                        #if InterGAS delete relative group_id others orders.
#                        if order.group_id and order.group_id > 0:
#                            #COMMENT: do it in Models with def delete(self, *args, **kw)?
#                            planed_intergas_orders = GASSupplierOrder.objects.filter(group_id=order.group_id)
#                            if planed_intergas_orders and planed_intergas_orders.count() >0:
#                                for intergas_order in planed_intergas_orders:
#                                    log.debug("AddOrderForm repeat delete intergas_previous_planed_orders: %s" % (intergas_order))
#                                    intergas_order.delete()
#WAS: INTERGAS 4
#                    #get new interGAS number if needed
#                    if _intergas_orders:
#                        x_obj.group_id = get_group_id()
#WAS: INTERGAS 5
#                        #InterGAS
#                        if _intergas_orders:
#                            for other_order in _intergas_orders:
#                                try:
#                                    other_order.datetime_start = x_obj.datetime_start
#                                    other_order.datetime_end = x_obj.datetime_end
#                                    other_order.delivery.date = x_obj.delivery.date
#                                    x_other_obj = GetNewOrder(other_order, None)
#                                    if x_other_obj:
#                                        #COMMENT domthu: Don't understand why .save() not return true?
#                                        if x_other_obj.save():
#                                            log.debug("another repeat created order: %s " % (x_other_obj))
#                                        else:
#                                            log.debug("another repeat NOT created: pact %s, start %s , end %s , delivery %s" % (x_other_obj.pact, x_other_obj.datetime_start, x_other_obj.datetime_end, x_other_obj.delivery.date))
#                                except Exception,e:
#                                    log.debug("another repeat NOT created order ERROR: %s " % (e))
#WAS: INTERGAS 6
#                            , ('intergas', 'intergas_grd')

#-------------------------------------------------------------------------------


class EditOrderForm(BaseOrderForm):


    def __init__(self, request, *args, **kw):

        #log.debug("EditOrderForm")

        super(EditOrderForm, self).__init__(request, *args, **kw)

        #SOLIDAL PACT
        pact = request.resource.pact
        delivery = request.resource.delivery
        ref = request.resource.referrer_person
        if ref:
            #control if queryset not empty.
            self.fields['referrer_person'].initial = ref
        if request.resource.datetime_end:
            self.fields['datetime_end'].initial = request.resource.datetime_end
        if delivery and delivery.date:
            self.fields['delivery_datetime'].initial = delivery.date

    def save(self):

        if self.cleaned_data.get('delivery_datetime'):
            d = self.get_delivery()
            self.instance.delivery = d

        if self.cleaned_data.get('withdrawal_datetime'):
            w = self.get_withdrawal()
            self.instance.withdrawal = w

        return super(EditOrderForm, self).save()

    class Meta:
        model = GASSupplierOrder
        fields = ['datetime_start', 'datetime_end', 'referrer_person']

        gf_fieldsets = [(None, {
            'fields' : [ ('datetime_start', 'datetime_end')
                            , 'delivery_datetime'
                            , 'referrer_person'
            ]
        })]

def form_class_factory_for_request(request, base):
    """Return appropriate form class basing on GAS configuration
    and other request parameters if needed"""

    #log.debug("OrderForm--> form_class_factory_for_request")
    fields = copy.deepcopy(base.Meta.fields)
    gf_fieldsets = copy.deepcopy(base.Meta.gf_fieldsets)
    attrs = {}
    gas = request.resource.gas

    if gas:

        if gas.config.use_withdrawal_place:
            gf_fieldsets[0][1]['fields'].append('withdrawal_referrer_person')
            attrs.update({
                'withdrawal_referrer' : forms.ModelChoiceField(
                    queryset=Person.objects.none(), 
                    required=False
                ),
            })

        if gas.config.can_change_delivery_place_on_each_order:
            gf_fieldsets[0][1]['fields'].append(('delivery_city', 'delivery_addr_or_place'))
            attrs.update({
                'delivery_city' : forms.CharField(required=True, 
                    label=_('Delivery city'), 
                    initial=gas.city
                ),
                'delivery_addr_or_place': forms.CharField(
                    required=True, label=_('Delivery address or place'), 
                    initial=gas.headquarter
                ),
            })

        if gas.config.use_withdrawal_place:

            if gas.config.can_change_withdrawal_place_on_each_order:
                gf_fieldsets[0][1]['fields'].append((
                    'withdrawal_datetime', 'withdrawal_city', 
                    'withdrawal_addr_or_place')
                )
                attrs.update({
                    'withdrawal_datetime' : forms.SplitDateTimeField(
                        required=False, label=_('Withdrawal on/at'), 
                        widget=admin_widgets.AdminSplitDateTime
                    ),
                    'withdrawal_city' : forms.CharField(
                        required=True, label=_('Withdrawal city'), 
                        initial=gas.city
                    ),
                    'withdrawal_addr_or_place': forms.CharField(required=True, 
                        label=_('Withdrawal address or place'), 
                        initial=gas.headquarter
                    ),
                })


        attrs.update(Meta=type('Meta', (), {
            'model' : GASSupplierOrder,
            'fields' : fields,
            'gf_fieldsets' : gf_fieldsets
        }))
    return type('Custom%s' % base.__name__, (base,), attrs)


#-------------------------------------------------------------------------------


class GASSupplierOrderProductForm(forms.Form):

    id = forms.IntegerField(required=True, widget=forms.HiddenInput)
    enabled = forms.BooleanField(required=False)
    #log.debug("Create GASSupplierOrderProductForm (%s)" % id)

    def __init__(self, request, *args, **kw):
        super(GASSupplierOrderProductForm, self).__init__(*args, **kw)

    #@transaction.commit_on_success
    def save(self):

        #log.debug("Save GASSupplierOrderProductForm")
        id = self.cleaned_data.get('id')
        #log.debug("Save GASSupplierOrderProductForm id(%s)" % id)
        if id:
            enabled = self.cleaned_data.get('enabled')
            #log.debug("Save GASSupplierOrderProductForm enabled(%s)" % enabled)
            #Delete is ok for gsop that have gmo but: 
            #FIXME: if no gmo associated to gsop the field enabled remain always True?
            if not enabled:
                gsop = GASSupplierOrderProduct.objects.get(pk=id)
                log.debug("STO rendendo indisponibile (fuori stagione) un prodotto da un ordine aperto")
                log.debug(u"order(%s) %s  per prodotto(%s): %s |||| ordini gasmember: [Euro %s/amount %s/Gasisti %s]" % (
                    gsop.order.pk, gsop.order, id, gsop.product, gsop.tot_price, 
                    gsop.tot_amount, gsop.tot_gasmembers
                ))
                gsop.delete()



#-------------------------------------------------------------------------------


class SingleGASMemberOrderForm(forms.Form):
    """Return form class for row level operation on GSOP datatable"""

    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    #log.debug("Create SingleGASMemberOrderForm (%s)" % id)
    gssop_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    ordered_amount = forms.DecimalField(required=False, initial=0)
    ordered_price = forms.DecimalField(required=False, widget=forms.HiddenInput)
    note = forms.CharField(required=False, widget=forms.TextInput(), max_length=64)

    def __init__(self, request, *args, **kw):
        super(SingleGASMemberOrderForm, self).__init__(*args, **kw)
        self.fields['note'].widget.attrs['class'] = 'input_medium'
        self.__gm = request.resource.gasmember
        self.__gmusr = request.resource.gasmember.person.user
        self.__loggedusr = request.user

    def clean(self):
        cleaned_data = super(SingleGASMemberOrderForm, self).clean()

        #COMMENT LF: specifications say that every GASMember MUST
        #COMMENT LF: be bound to a User: so raise an Exception if not True
        if not self.__gmusr:
            raise DatabaseInconsistent(
                "Member %s is not bound to a valid User" % self.__gm
            )

        if self.__gmusr != self.__loggedusr:
            log.debug(u"------SingleGASMemberOrderForm (%s) not enabled for %s" % (
                self.__gmusr, self.__loggedusr
            ))
            raise forms.ValidationError(
                _(u"You %(logged)s are not authorized to make an order for %(person)s") % {
                    'logged' : u"(%s)" % self.__loggedusr, 
                    'person' :self.__gmusr
            })
        return cleaned_data

    def save(self):

        id = self.cleaned_data.get('id')
        if id:
            gmo = GASMemberOrder.objects.get(pk=id)
            gmo.ordered_price = self.cleaned_data.get('ordered_price')
            gmo.ordered_amount = self.cleaned_data.get('ordered_amount')
            gmo.note = self.cleaned_data.get('note')
            if gmo.ordered_amount == 0:
                gmo.delete()
                log.debug(u"STO CANCELLANDO un ordine gasista da widget quantita")
            else:
                gmo.save()
                log.debug(u"Product ho aggiornato un ordine gasista (%s) " % id)

        elif self.cleaned_data.get('ordered_amount'):
                gssop = GASSupplierOrderProduct.objects.get(pk=self.cleaned_data.get('gssop_id'))
                #retrieve if yet exist. Security to ensure non duplicate entry into database
                #But this is done into GASMemberOrder Model with set unique_together
                gmo = GASMemberOrder(
                        ordered_product = gssop,
                        ordered_price = self.cleaned_data.get('ordered_price'),
                        ordered_amount = self.cleaned_data.get('ordered_amount'),
                        note = self.cleaned_data.get('note'),
                        purchaser = self.__gm,
                )
                gmo.save()
                log.debug("Product ho creato un ordine gasista (%s) " % gmo.pk)

class BasketGASMemberOrderForm(forms.Form):
    """Return form class for row level operation on GMO datatable"""

    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    #log.debug("Create BasketGASMemberOrderForm (%s)" % id)
    gm_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    gsop_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    ordered_amount = forms.DecimalField(required=False, initial=0)
    ordered_price = forms.DecimalField(required=False, widget=forms.HiddenInput)
    enabled = forms.BooleanField(required=False)

    def __init__(self, request, *args, **kw):
        super(BasketGASMemberOrderForm, self).__init__(*args, **kw)
        self.__gm = request.resource.gasmember
        self.__gmusr = request.resource.gasmember.person.user
        self.__loggedusr = request.user

    def clean(self):
        cleaned_data = super(BasketGASMemberOrderForm, self).clean()

        #COMMENT LF: specifications say that every GASMember MUST
        #COMMENT LF: be bound to a User: so raise an Exception if not True
        if not self.__gmusr:
            raise DatabaseInconsistent(
                "Member %s is not bound to a valid User" % self.__gm
            )

        if self.__gmusr != self.__loggedusr:
            log.debug("------BasketGASMemberOrderForm (%s) not enabled for %s" % (
                self.__gmusr,self.__loggedusr
            ))
            raise forms.ValidationError(
                _("You %(logged)s are not authorized to make an order for %(person)s") % {
                    'logged' : u"(%s)" % self.__loggedusr, 
                    'person' :self.__gmusr
            })
        return cleaned_data


    def save(self):

        if not self.__gmusr or self.__gmusr != self.__loggedusr:
            log.debug("------BasketGASMemberOrderForm (%s) not enabled for %s" % (
                self.__gmusr,self.__loggedusr
            ))
            return
        id = self.cleaned_data.get('id')
        gm_id = self.cleaned_data.get('gm_id')
        gsop_id = self.cleaned_data.get('gsop_id')
        enabled = self.cleaned_data.get('enabled')
        if id:
            gmo = GASMemberOrder.objects.get(pk=id)
#            if gm_id and gm_id != gmo.purchaser.pk:
#                print "Qualcosa non va con: GASmember"
#                return ""
            gmo.ordered_price = self.cleaned_data.get('ordered_price')
            gmo.ordered_amount = self.cleaned_data.get('ordered_amount')
            #log.debug("BasketGASMemberOrderForm (%s) enabled = %s" % (gmo.pk,enabled))
            if gmo.ordered_amount == 0:
                log.debug(u"Basket STO CANCELLANDO un ordine gasista da widget quantita")
                gmo.delete()
            elif enabled:
                log.debug(u"Basket STO CANCELLANDO un ordine gasista da check enabled")
                gmo.delete()
            else:
                log.debug(u"Basket ho aggiornato un ordine gasista (%s) " % id)
                gmo.save()
