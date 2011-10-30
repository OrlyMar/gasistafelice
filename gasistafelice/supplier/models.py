"""These models include information about Products, Suppliers, Producers.

These are fundamental DES data to rely on. They represent market offering.

Models here rely on base model classes.

Definition: `Vocabolario - Fornitori <http://www.jagom.org/trac/REESGas/wiki/BozzaVocabolario#Fornitori>`__ (ITA only)
"""

from django.db import models
from django.utils.translation import ugettext, ugettext_lazy as _
from django.contrib.auth.models import User
from django.conf import settings

from history.models import HistoricalRecords

from flexi_auth.utils import register_parametric_role
from flexi_auth.models import ParamRole
from flexi_auth.exceptions import WrongPermissionCheck

from gasistafelice.exceptions import NoSenseException
from gasistafelice.lib import ClassProperty
from gasistafelice.lib.fields.models import CurrencyField
from gasistafelice.lib.fields import display

from gasistafelice.base.const import SUPPLIER_FLAVOUR_LIST, ALWAYS_AVAILABLE
from gasistafelice.base.utils import get_resource_icon_path
from gasistafelice.base.models import PermissionResource, Person, Place, Contact
from gasistafelice.des.models import DES, Siteattr

from gasistafelice.consts import SUPPLIER_REFERRER
from gasistafelice.gas import signals

from decimal import Decimal
import logging

log = logging.getLogger(__name__)

class Supplier(models.Model, PermissionResource):
    """An actor having a stock of Products for sale to the DES."""

    name = models.CharField(max_length=128, verbose_name=_("name")) 
    seat = models.ForeignKey(Place, null=True, blank=True, verbose_name=_("seat"))
    vat_number = models.CharField(max_length=128, unique=True, null=True, verbose_name=_("VAT number")) #TODO: perhaps a custom field needed here ? (for validation purposes)
    website = models.URLField(verify_exists=True, blank=True, verbose_name=_("web site"))
    agent_set = models.ManyToManyField(Person, through="SupplierAgent")
    flavour = models.CharField(max_length=128, choices=SUPPLIER_FLAVOUR_LIST, default=SUPPLIER_FLAVOUR_LIST[0][0], verbose_name=_("flavour"))
    certifications = models.ManyToManyField('Certification', null=True, blank=True, verbose_name = _('certifications'))
    logo = models.ImageField(upload_to=get_resource_icon_path, null=True, blank=True)
    contact_set = models.ManyToManyField(Contact, null=True, blank=True)

    #FUTURE TODO des = models.ManyToManyField(DES, null=True, blank=True)

    history = HistoricalRecords()
    
    class Meta :
        verbose_name = _('supplier')
        verbose_name_plural = _('suppliers')        
        ordering = ('name',)

    def __unicode__(self):
        return unicode(self.name)

    def setup_roles(self):
        # register a new `SUPPLIER_REFERRER` Role for this Supplier
        register_parametric_role(name=SUPPLIER_REFERRER, supplier=self) 

    @property
    def icon(self):
        return self.logo or super(Supplier, self).icon

    #-- Contacts --#

    @property
    def contacts(self):
        return self.contact_set.all() | Contact.objects.filter(person__in=self.info_people)

    @property
    def preferred_email_contacts(self):
        pref_contacts = self.contact_set.filter(is_preferred=True)
        if pref_contacts.count():
            return pref_contacts
        else:
            return super(GAS, self).preferred_email_contacts()

    #-- Resource API --#

    @property
    def des(self):
        return Siteattr.get_site()

    @property
    def parent(self):
        return self.des

    @property
    def suppliers(self):
        return Supplier.objects.filter(pk=self.pk)

    @property
    def supplier(self):
        return self

    @property
    def referrers(self):
        """All User linked as platform operators for this resource.

        User who have role SUPPLIER_REFERRER."""

        # retrieve 'Supplier Referrer' parametric role for this supplier
        pr = ParamRole.get_role(SUPPLIER_REFERRER, supplier=self)
        # retrieve all Users having this role
        return pr.get_users()

    @property
    def info_people(self):
        """Return Person that can give info on this resource QuerySet."""
        return self.agent_set.all()

    @property
    def persons(self):
        """Return evryone (Person) related to this resource."""
        return self.info_people | self.referrers_people

    @property
    def stocks(self):
        return self.stock_set.all()

    @property
    def pacts(self):
        return self.pact_set.all()

    @property
    def pact(self):
        raise NoSenseException("calling supplier.pact is a no-sense. Supplier is related to more than one pact")

    @property
    def orders(self):
        from gasistafelice.gas.models.order import GASSupplierOrder
        return GASSupplierOrder.objects.filter(pact__in=self.pacts)

    @property
    def order(self):
        raise NotImplementedError("calling supplier.order is a no-sense. Supplier is related to more than one order")

    @property
    def gas_list(self):
        from gasistafelice.gas.models.base import GAS
        return GAS.objects.filter(pact_set__in=self.pacts)

    @property
    def gas(self):
        raise NotImplementedError("calling supplier.gas is a no-sense. Supplier is related to more than one gas")

    @property
    def products(self):
        """All products _supplied_ by this supplier"""
        #TODO: we have to differentiate a way to see all products __produced__ by this supplier
        return Product.objects.filter(stock_set__in=self.stocks).distinct()

    @property
    def categories(self):
        """All categories _supplied_ by this supplier"""
        #TODO: we have to differentiate a way to see all categories __produced__ by this supplier
        return ProductCategory.objects.filter(product_set__in=self.products).distinct()

    #-------------- Authorization API ---------------#
    
    # Table-level CREATE permission    
    @classmethod
    def can_create(cls, user, context):
        # Who can create a new supplier in a DES ?
        # * DES administrators
        # * referrers and administrators of every GAS in the DES
        try:
            des = context['des']
            all_gas_referrers = User.objects.none()
            #TOERASE: all_gas_referrers_tech = set()
            for gas in des.gas_list:
                all_gas_referrers = all_gas_referrers | gas.referrers
                #TOERASE: all_gas_referrers_tech = all_gas_referrers_tech | gas.tech_referrers
            allowed_users = des.admins | all_gas_referrers #TOERASE: | all_gas_referrers_tech 
            return user in allowed_users
        except KeyError:
            raise WrongPermissionCheck('CREATE', cls, context)   
 
    # Row-level EDIT permission
    def can_edit(self, user, context):
        # Who can edit details of a Supplier in a DES ?
        # * DES administrators
        # * referrers for that supplier        
        allowed_users = self.des.admins | self.referrers
        return user in allowed_users 
    
    # Row-level DELETE permission
    def can_delete(self, user, context):
        # Who can remove a supplier from a DES ?
        # * DES administrators
        allowed_users = self.des.admins
        return user in allowed_users 
    
    #-----------------------------------------------#       

    def clean(self):
        self.name = self.name.strip()
        self.flavour = self.flavour.strip()
        #TODO placeholder: dominique check flavour is in appropriate choices
    
        return super(Supplier, self).clean()

    def setup_data(self):
        # Needed to be called by fixture import
        try:
            self.config
        except SupplierConfig.DoesNotExist:
            self.config = SupplierConfig.objects.create(supplier=self)

    display_fields = (
        seat, vat_number, website, flavour, 
        display.ResourceList(name="info_people", verbose_name=_("Contacts")),
        display.ResourceList(name="referrers_people", verbose_name=_("Platform referrers")),
        display.ResourceList(name="pacts", verbose_name=_("Pacts")),
    )

class SupplierConfig(models.Model):
    """
    Encapsulate here supplier settings and configuration facilities
    """

    # Link to parent class
    supplier = models.OneToOneField(Supplier, related_name="config")

    products_made_by_set = models.ManyToManyField(Supplier, verbose_name=_("products made by"), help_text=_("Select here producers of products you sell. YOU will be always enabled in this list"))

    receive_order_via_email_on_finalize = models.BooleanField(verbose_name=_("receive order via email on finalize"), default=True, help_text=_("Check here if you want to receive order via mail when finalized"))

    def setup_data(self):

        if self.supplier not in self.products_made_by_set.all():
           self.products_made_by_set.add(self.supplier)


class SupplierAgent(models.Model):
    """Relation between a `Supplier` and a `Person`.

    If you need information on the Supplier, ask this person.
    This is not necessarily a user in the system. You can consider it just as a contact.
    """

    supplier = models.ForeignKey(Supplier)
    person = models.ForeignKey(Person)
    job_title = models.CharField(max_length=256, blank=True)
    job_description = models.TextField(blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = _('supplier agent')
        verbose_name_plural = _('supplier agents')

    @property
    def parent(self):
        return self.supplier

    def clean(self):
        self.job_title = self.job_title.strip()
        self.job_description = self.job_description.strip()
        return super(SupplierAgent, self).clean()

# COMMENT fero: this should be related to EDIT and CREATE permissions for related Supplier object
#    #-------------- Authorization API ---------------#
#    
#    # Table-level CREATE permission    
#    @classmethod
#    def can_create(cls, user, context):
#        # Who can add a new referrer for an existing supplier in a DES ?
#        # * DES administrators
#        # * referrers and administrators of every GAS in the DES
#        try:
#            des = context['des']
#            all_gas_referrers = set()
#            #TOERASE: new  gas.referrers returns also tech_referrers. Answer to question: who is GAS operator in this platform?
#            #TOERASE: all_gas_referrers_tech = set()
#            for gas in des.gas_list:
#                all_gas_referrers = all_gas_referrers | gas.referrers
#                #TOERASE all_gas_referrers_tech = all_gas_referrers_tech | gas.tech_referrers
#            allowed_users = des.admins | all_gas_referrers #TOERASE | all_gas_referrers_tech 
#            return user in allowed_users
#        except KeyError:
#            raise WrongPermissionCheck('CREATE', cls, context)
#        
#    # Row-level EDIT permission
#    def can_edit(self, user, context):
#        # Who can edit details of a supplier referrer ?
#        # * DES administrators
#        # * the referrer itself
#        allowed_users = set(self.supplier.des.admins) | set([self.person.user]) 
#        return user in allowed_users 
#    
#    # Row-level DELETE permission
#    def can_delete(self, user, context):
#        # Who can delete a supplier referrer ?
#        # * DES administrators
#        # * other referrers for that supplier  
#        allowed_users = self.supplier.des.admins | self.supplier.referrers
#        return user in allowed_users 
    

    
class Certification(models.Model, PermissionResource):

    name = models.CharField(max_length=128, unique=True,verbose_name=_('name')) 
    description = models.TextField(blank=True,verbose_name=_('description'))

    history = HistoricalRecords()

    def __unicode__(self):
        return self.name

    def clean(self):
        self.name = self.name.strip()
        self.description = self.description.strip()
        return super(Certification, self).clean()

    class Meta:
        verbose_name = _("certification")
        verbose_name_plural = _("certifications")

    #-------------- Authorization API ---------------#
    
    # Table-level CREATE permission    
    @classmethod
    def can_create(cls, user, context):
        # Who can add a new certification ?
        # * DES administrators
        try:            
            allowed_users = DES.admins_all()
            return user in allowed_users
        except KeyError:
            raise WrongPermissionCheck('CREATE', cls, context)   
 
    # Row-level EDIT permission
    def can_edit(self, user, context):
        # Who can edit details of an existing certification ?
        # * DES administrators    
        allowed_users = DES.admins_all()    
        return user in allowed_users 
    
    # Row-level DELETE permission
    def can_delete(self, user, context):
        # Who can delete an existing certification ?
        # * DES administrators
        allowed_users = DES.admins_all()
        return user in allowed_users     
        
    #-----------------------------------------------#


class ProductCategory(models.Model, PermissionResource):

    # The name is in the form MAINCATEGORY::SUBCATEGORY
    # accept arbitrary sublevels

    name = models.CharField(max_length=128, unique=True, blank=False,verbose_name=_('name'))
    description = models.TextField(blank=True,verbose_name=_('description'))
    image = models.ImageField(upload_to=get_resource_icon_path, null=True, blank=True,verbose_name=_('image'))

    history = HistoricalRecords()

    class Meta:
        verbose_name=_('Product category')
        verbose_name_plural = _("Product categories")

    def __unicode__(self):
        return self.name
    
    @property
    def icon(self):
        return self.image or super(ProductCategory, self).icon

    def save(self, *args, **kw):

        if self.name == settings.DEFAULT_CATEGORY_CATCHALL:
            raise ValueError(_("Cannot change default category, nor create a new one with the same name"))

        super(ProductCategory, self).save(*args, **kw)

    @property
    def icon(self):
        return self.image or super(ProductCategory, self).icon

    #-------------- Authorization API ---------------#
    
    # Table-level CREATE permission    
    @classmethod
    def can_create(cls, user, context):
        # Who can create a new category for products ?
        # * DES administrators
        try:  
            allowed_users = DES.admins_all()          
            return user in allowed_users
        except KeyError:
            raise WrongPermissionCheck('CREATE', cls, context)   
 
    # Row-level EDIT permission
    def can_edit(self, user, context):
        # Who can edit details of an existing category ?
        # * DES administrators  
        allowed_users = DES.admins_all()       
        return user in allowed_users 
    
    # Row-level DELETE permission
    def can_delete(self, user, context):
        # Who can delete an existing category ?
        # * DES administrators
        allowed_users = DES.admins_all()
        return user in allowed_users

    #-----------------------------------------------#

    @property
    def categories(self):
        return ProductCategory.objects.filter(pk=self.pk)

class ProductMU(models.Model, PermissionResource):
    """Measurement unit for a Product.

    A measure unit is recognized as a standard. So it is provided 
    as a fixture "as is" and can be changed only by DES admins.

    If a measure unit for a Product is not specified, software will 
    not able to perform conversions, thus cannot compute price-per-liter,
    or price-per-kilo. 
    
    Implemented as a separated entity like GasDotto software. 
    Kudos to Roberto `madbob` Guido. 
    Then we evolved in decoupling Measure Unit from Product Unit.
    
    # examples: gr, Kg, Lt, m
    """
    
    name = models.CharField(max_length=32, unique=True)
    symbol = models.CharField(max_length=5, unique=True)

    history = HistoricalRecords()

    def __unicode__(self):
        return self.symbol
    
    class Meta():
        verbose_name=_("measure unit")
        verbose_name_plural=_("measure units")
    
        #-------------- Authorization API ---------------#
    
    # Table-level CREATE permission    
    @classmethod
    def can_create(cls, user, context):
        # Who can create a new unit of measure for products ?
        # * DES administrators
        try:            
            allowed_users = DES.admins_all()
            return user in allowed_users
        except KeyError:
            raise WrongPermissionCheck('CREATE', cls, context)   
 
    # Row-level EDIT permission
    def can_edit(self, user, context):
        # Who can edit details of an existing unit of measure for products ?
        # * DES administrators         
        allowed_users = DES.admins_all()
        return user in allowed_users 
    
    # Row-level DELETE permission
    def can_delete(self, user, context):
        # Who can delete an existing unit of measure for products ?
        # * DES administrators
        allowed_users = DES.admins_all()
        return user in allowed_users

    #-----------------------------------------------#

class ProductPU(models.Model, PermissionResource):
    """Product unit for a Product.

    Represents how the product is sold.
    Limit ProdutPU creation and update to DES admins 
    and GAS_REFERRER_TECHs TODO TO BE DONE: seldon
    If this is not enough, we could evaluate another policy that
    involves SUPPLIER_REFERRERs.

    examples: box, slice, bottle, tanks
    it can be also the same as a measure unit.
    
    """

    name = models.CharField(max_length=32, unique=True)
    symbol = models.CharField(max_length=5, unique=True)
    description = models.TextField(blank=True)

    history = HistoricalRecords()

    def __unicode__(self):
        return self.symbol
    
    class Meta():
        verbose_name=_("product unit")
        verbose_name_plural=_("product units")
    
        #-------------- Authorization API ---------------#
    
    # Table-level CREATE permission    
    @classmethod
    def can_create(cls, user, context):
        # Who can create a new unit of measure for products ?
        # * DES administrators
        try:            
            allowed_users = DES.admins_all()
            return user in allowed_users
        except KeyError:
            raise WrongPermissionCheck('CREATE', cls, context)   
 
    # Row-level EDIT permission
    def can_edit(self, user, context):
        # Who can edit details of an existing unit of measure for products ?
        # * DES administrators         
        allowed_users = DES.admins_all()
        return user in allowed_users 
    
    # Row-level DELETE permission
    def can_delete(self, user, context):
        # Who can delete an existing unit of measure for products ?
        # * DES administrators
        allowed_users = DES.admins_all()
        return user in allowed_users

    #-----------------------------------------------#

def category_catchall():
    return ProductCategory.objects.get(name=settings.DEFAULT_CATEGORY_CATCHALL)

class Product(models.Model, PermissionResource):

    # Some producers don't have product codification. 
    # That's why code could be blank AND null. See save() method
    code = models.CharField(max_length=128, unique=True, blank=True, null=True, verbose_name=_('code'), help_text=_("Identification provided by the producer"))

    producer = models.ForeignKey(Supplier, related_name="produced_product_set", verbose_name = _("producer"))

    # Resource API
    category = models.ForeignKey(ProductCategory, blank=True, related_name="product_set", verbose_name = _("category"), default=category_catchall)

    # Measure unit, it can be null in order to make it easier to define 
    # a new product. If a user specifies a `pu` which is also a `mu`,
    # the software assigns:
    # * `instance.muppu` = 1
    # * `instance.mu` = `instance.pu`
    # thus avoiding NULL values for `mu` itself
    # See `ProductMU` doc for more details
    mu = models.ForeignKey(ProductMU, null=True, verbose_name=_("measure unit"), blank=True)

    # Product unit: how is sell this product:
    # box, tanks, bottles, or even a measure unit
    # This must be specified.
    pu = models.ForeignKey(ProductPU, verbose_name=_("product unit"))
    muppu = models.DecimalField(verbose_name=_('measure unit per product unit'), 
                decimal_places=2, max_digits=6, default=Decimal("1.00"),
                help_text=_("How many measure units fit in your product unit?")
    )
    muppu_is_variable = models.BooleanField(verbose_name=_("variable volume"), default=False,
                help_text=_("Check this if measure units per product unit is not exact")
    )

    vat_percent = models.DecimalField(max_digits=3, decimal_places=2, 
                default=Decimal("0.2"), verbose_name=_('vat percent')
    )

    name = models.CharField(max_length=128, verbose_name = _("name"))
    description = models.TextField(blank=True, verbose_name = _("description"))
    
    history = HistoricalRecords()
    
    class Meta:
        verbose_name = _('product')
        verbose_name_plural = _('products')

    def __unicode__(self):
        return self.name

    def clean(self):

        # Set default DES category for a product
        if not self.category:
            self.category = category_catchall()

        return super(Product, self).clean()
        
    @property
    def uuid(self):
        raise NotImplementedError("""UUID stuff MUST be developed as external app: 
it has to take care of UUIDs for every resource of the platform. To be effective it
MUST interact with a global UUIDs registry on the Internet. It is useful only if
the UUID is unique in the world. Annotated as "future todo" see
http://www.jagom.org/trac/reesgas/ticket/157
.
""")

    @property
    def referrers(self):
        return self.producer.referrers
  
    def save(self, *args, **kw):

        created = False
        if not self.pk:
            created = True
        
        return super(Product, self).save(*args, **kw)

        if created:
            self.config = SupplierConfig.objects.create(supplier=self)

    #-- Resource API --#

    @property
    def products(self):
        return Product.objects.filter(pk=self.pk)

    @property
    def stocks(self):
        return self.stock_set.all()

    @property
    def categories(self):
        return ProductCategory.objects.filter(product_set__in=[self])

    @property
    def suppliers(self):
        return Supplier.objects.filter(stock_set__in=self.stocks)

    @property
    def orders(self):
        return GASSupplierOrder.objects.filter(stock_set__in=self.stocks)

    #-------------- Authorization API ---------------#
    
    # Table-level CREATE permission    
    @classmethod
    def can_create(cls, user, context):
        # Who can add a new product to a supplier catalog ?
        # * referrers for that supplier
        try:
            supplier = context['supplier']
            allowed_users = supplier.referrers
            return user in allowed_users
        except KeyError:
            raise WrongPermissionCheck('CREATE', cls, context)   
 
    # Row-level EDIT permission
    def can_edit(self, user, context):
        # Who can edit details of a product in a supplier catalog ?
        # * referrers for that supplier
        allowed_users = self.producer.referrers
        return user in allowed_users 
    
    # Row-level DELETE permission
    def can_delete(self, user, context):
        # Who can delete a product from a supplier catalog ?
        # * referrers for that supplier
        allowed_users = self.producer.referrers
        return user in allowed_users 
    
    #-----------------------------------------------#

class SupplierStock(models.Model, PermissionResource):
    """A Product that a Supplier offers in the DES marketplace.
        
       Includes price, order constraints and availability information.

    # TODO UNITTEST
    >> from supplier.models import *
    >> ss = SupplierStock.objects.get(pk=1)
    >> isinstance(ss, SupplierStock)
    True
    >> ss.has_changed_availability
    False
    >> ss.amount_available = ss.amount_available + 1
    >> ss.has_changed_availability
    True

    """

    # Resource API
    supplier = models.ForeignKey(Supplier, related_name="stock_set", verbose_name = _('supplier'))
    # Resource API
    product = models.ForeignKey(Product, related_name="stock_set", verbose_name = _('product'))

    # Custom category defined by Supplier
    supplier_category = models.ForeignKey("SupplierProductCategory", null=True, blank=True, verbose_name = _('supplier category'))
    image = models.ImageField(upload_to=get_resource_icon_path, null=True, blank=True, verbose_name = _('image'))

    price = CurrencyField(verbose_name=_("price"))

    code = models.CharField(verbose_name=_("code"), max_length=128, null=True, blank=True, help_text=_("Product supplier identifier"))
    amount_available = models.PositiveIntegerField(verbose_name=_("availability"), default=ALWAYS_AVAILABLE)

    ## constraints posed by the Supplier on orders issued by *every* GAS
    # minimum amount of Product units a GAS can order 
    units_minimum_amount = models.PositiveIntegerField(default=1, verbose_name = _('units minimum amount'))

    # increment step (in Product units) for amounts exceeding minimum; 
    # useful when a Product ships in packages containing multiple units.
    units_per_box = models.DecimalField(verbose_name=_("units per box"), 
                        default=1, max_digits=5, decimal_places=2
    )

    ## constraints posed by the Supplier on orders issued by *every* GASMember
    ## they act as default when creating a GASSupplierSolidalPact
    # minimum amount of Product units a GASMember can order 
    detail_minimum_amount = models.DecimalField(null=True, blank=True, 
                        default=1, verbose_name = _('detail minimum amount'),
                        max_digits=5, decimal_places=2
    )

    # increment step (in Product units) for amounts exceeding minimum; 
    # useful when a Product has a fixed step of increment
    detail_step = models.DecimalField(null=True, blank=True, 
                        max_digits=5, decimal_places=2,
                        verbose_name=_("detail step"), default=1
    )

    # How the Product will be delivered
    delivery_notes = models.TextField(blank=True, default='', verbose_name = _('delivery notes'))

    #TODO: Notify system

    history = HistoricalRecords()

    class Meta:
        verbose_name = _('supplier stock')
        verbose_name_plural = _('supplier stocks')
        #Fixtures do not work: to be checked and then re-enabled TODO
        #unique_together = (('code', 'supplier'),)

    @ClassProperty
    @classmethod
    def resource_type(cls):
        return "stock" 

    def __init__(self, *args, **kw):
        super(SupplierStock, self).__init__(*args, **kw)
        self._msg = None

    def __unicode__(self):
        return u'%s (by %s)' % (unicode(self.product), unicode(self.supplier))

    @property
    def net_price(self):
        return self.price/(1 + self.product.vat_percent)

    @property
    def icon(self):
        return self.image or self.category.icon

    @property
    def producer(self):
        return self.product.producer

    @property
    def category(self):
        return self.product.category

    @property
    def description(self):
        return self.product.description

    @property
    def name(self):
        return unicode(self)

    @property
    def vat_percent(self):
        return self.product.vat_percent
    @property
    def availability(self):
        return bool(self.amount_available)

    @property
    def has_changed_availability(self):
        try:
            ss = SupplierStock.objects.get(pk=self.pk)
            if not ss is None:
                return bool(self.amount_available != ss.amount_available)
            else:
                return False
        except SupplierStock.DoesNotExist:
            return False

    @property
    def has_changed_price(self):
        try:
            ss = SupplierStock.objects.get(pk=self.pk)
            if not ss is None:
                return bool(self.price != ss.price)
            else:
                return False
        except SupplierStock.DoesNotExist:
            return False

    @property
    def message(self):
        """getter property for internal message from model."""
        return self._msg

    def save(self, *args, **kwargs):

        # if `code` is set to an empty string, set it to `None`, instead, before saving,
        # so it's stored as NULL in the DB, avoiding integrity issues.
        if not self.code:
            self.code = None

        # CASCADING
        if self.has_changed_availability:
            self._msg = []
            self._msg.append('Availability has changed for product %s' %  self.product)
            #For each GASSupplierStock (present for each GASSupplierSolidalPact) set new availability and save
            for gss in self.gasstocks:
                if (self.availability != gss.enabled):
                    gss.enabled = self.availability
                    gss.save()
                    if not gss.enabled:
                        signals.gasstock_product_disabled.send(sender=gss)
                    else:
                        signals.gasstock_product_enabled.send(sender=gss)
                    
                    if gss.message is not None:
                        self._msg.extend(gss.message)
            self._msg.append('Ended(%d)' % self.gasstocks.count())
            log.debug(self._msg)

        if self.has_changed_price:
            for gsop in self.orderable_products:
                gsop.order_price = self.price
                gsop.save()

            for gmo in self.basket:
                if gmo.has_changed:
                    signals.gmo_price_update.send(sender=gmo)
            
        super(SupplierStock, self).save(*args, **kwargs)

    #-- Resource API --#

    @property
    def gasstocks(self):
        return self.gasstock_set.all()
    
    @property
    def orders(self):
        from gasistafelice.gas.models import GASSupplierOrder
        return GASSupplierOrder.objects.filter(gasstock_set__in=self.gasstocks)

    @property
    def orderable_products(self):
        from gasistafelice.gas.models import GASSupplierOrderProduct
        return GASSupplierOrderProduct.objects.filter(order__in=self.orders.open())

    @property
    def ordered_products(self):
        from gasistafelice.gas.models import GASMemberOrder
        return GASMemberOrder.objects.filter(order__in=self.orders)

    @property
    def basket(self):
        from gasistafelice.gas.models import GASMemberOrder
        return GASMemberOrder.objects.filter(order__in=self.orders.open())

    @property
    def stocks(self):
        return SupplierStock.objects.filter(pk=self.pk)

    @property
    def stock(self):
        return self
    #-------------- Authorization API ---------------#
    
    # Table-level CREATE permission    
    @classmethod
    def can_create(cls, user, context):
        # Who can add a new stock to a supplier catalog ?
        # * referrers for that supplier
        try:
            supplier = context['supplier']
            allowed_users = supplier.referrers
            return user in allowed_users
        except KeyError:
            raise WrongPermissionCheck('CREATE', cls, context)   
 
    # Row-level EDIT permission
    def can_edit(self, user, context):
        # Who can edit details of a stock in  a supplier catalog ?
        # * referrers for that supplier
        allowed_users = self.supplier.referrers
        return user in allowed_users 
    
    # Row-level DELETE permission
    def can_delete(self, user, context):
        # Who can delete a stock from  a supplier catalog ?
        # * referrers for that supplier
        allowed_users = self.supplier.referrers
        return user in allowed_users 
    
    #-----------------------------------------------#

    @property
    def display_price(self):
        return u"%(price)s (%(vat_name)s %(vat)s%%)" % {
            'price' : self.price,
            'vat_name' : _('VAT'),
            'vat' : self.vat_percent*100,
        }

    display_fields = (
        supplier,
        models.TextField(name="description", verbose_name=_("Description")),
        code,
        models.CharField(max_length=32, name="display_price", verbose_name=_("Price")),
        display.Resource(name="category", verbose_name=_("Category")),
        supplier_category,
        detail_minimum_amount, detail_step, 
        models.BooleanField(max_length=32, name="availability", verbose_name=_("Availability")),
    )


class SupplierProductCategory(models.Model):
    """Let supplier to specify his own categories for products he sells.

    This is useful to know WHICH categories a supplier CAN sell,
    and so limiting the choice in product selections."""

    supplier = models.ForeignKey(Supplier)
    name = models.CharField(verbose_name=_('name'), max_length=128)
    sorting = models.PositiveIntegerField(blank=True, null=True)

    def __unicode__(self):
        return self.name
    
    #-------------- Authorization API ---------------#
    
    # Table-level CREATE permission    
    @classmethod
    def can_create(cls, user, context):
        # Who can add a new supplier-specific category ?
        # * referrers for that supplier
        try:
            supplier = context['supplier']
            allowed_users = supplier.referrers
            return user in allowed_users
        except KeyError:
            raise WrongPermissionCheck('CREATE', cls, context)   
 
    # Row-level EDIT permission
    def can_edit(self, user, context):
        # Who can edit details of a supplier-specific category ?
        # * referrers for that supplier
        allowed_users = self.supplier.referrers
        return user in allowed_users 
    
    # Row-level DELETE permission
    def can_delete(self, user, context):
        # Who can delete a supplier-specific category ?
        # * referrers for that supplier
        allowed_users = self.supplier.referrers
        return user in allowed_users 
    
    #-----------------------------------------------#
