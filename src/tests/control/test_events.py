import datetime
from decimal import Decimal

from tests.base import SoupTest, extract_form_fields

from pretix.base.models import (
    Event, EventPermission, Organizer, OrganizerPermission, User,
)
from pretix.testutils.mock import mocker_context


class EventsTest(SoupTest):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('dummy@dummy.dummy', 'dummy')
        self.orga1 = Organizer.objects.create(name='CCC', slug='ccc')
        self.orga2 = Organizer.objects.create(name='MRM', slug='mrm')
        self.event1 = Event.objects.create(
            organizer=self.orga1, name='30C3', slug='30c3',
            date_from=datetime.datetime(2013, 12, 26, tzinfo=datetime.timezone.utc),
            plugins='pretix.plugins.banktransfer,tests.testdummy'
        )
        self.event2 = Event.objects.create(
            organizer=self.orga1, name='31C3', slug='31c3',
            date_from=datetime.datetime(2014, 12, 26, tzinfo=datetime.timezone.utc),
        )
        self.event3 = Event.objects.create(
            organizer=self.orga2, name='MRMCD14', slug='mrmcd14',
            date_from=datetime.datetime(2014, 9, 5, tzinfo=datetime.timezone.utc),
        )
        OrganizerPermission.objects.create(organizer=self.orga1, user=self.user)
        EventPermission.objects.create(event=self.event1, user=self.user, can_change_items=True,
                                       can_change_settings=True)
        self.client.login(email='dummy@dummy.dummy', password='dummy')

    def test_event_list(self):
        doc = self.get_doc('/control/events/')
        tabletext = doc.select("#page-wrapper .table")[0].text
        self.assertIn("30C3", tabletext)
        self.assertNotIn("31C3", tabletext)
        self.assertNotIn("MRMCD14", tabletext)

    def test_settings(self):
        doc = self.get_doc('/control/event/%s/%s/settings/' % (self.orga1.slug, self.event1.slug))
        doc.select("[name=date_to]")[0]['value'] = "2013-12-30 17:00:00"
        doc.select("[name=settings-max_items_per_order]")[0]['value'] = "12"
        print(extract_form_fields(doc.select('.container-fluid form')[0]))

        doc = self.post_doc('/control/event/%s/%s/settings/' % (self.orga1.slug, self.event1.slug),
                            extract_form_fields(doc.select('.container-fluid form')[0]))
        assert len(doc.select(".alert-success")) > 0
        assert doc.select("[name=date_to]")[0]['value'] == "2013-12-30 17:00:00"
        assert doc.select("[name=settings-max_items_per_order]")[0]['value'] == "12"

    def test_plugins(self):
        doc = self.get_doc('/control/event/%s/%s/settings/plugins' % (self.orga1.slug, self.event1.slug))
        self.assertIn("PayPal", doc.select(".form-plugins")[0].text)
        self.assertIn("Enable", doc.select("[name=plugin:pretix.plugins.paypal]")[0].text)

        doc = self.post_doc('/control/event/%s/%s/settings/plugins' % (self.orga1.slug, self.event1.slug),
                            {'plugin:pretix.plugins.paypal': 'enable'})
        self.assertIn("Disable", doc.select("[name=plugin:pretix.plugins.paypal]")[0].text)

        doc = self.post_doc('/control/event/%s/%s/settings/plugins' % (self.orga1.slug, self.event1.slug),
                            {'plugin:pretix.plugins.paypal': 'disable'})
        self.assertIn("Enable", doc.select("[name=plugin:pretix.plugins.paypal]")[0].text)

    def test_live_disable(self):
        self.event1.live = False
        self.event1.save()
        self.post_doc('/control/event/%s/%s/live/' % (self.orga1.slug, self.event1.slug),
                      {'live': 'false'})
        self.event1.refresh_from_db()
        assert not self.event1.live

    def test_live_ok(self):
        self.event1.items.create(name='Test', default_price=5)
        self.event1.settings.set('payment_banktransfer__enabled', True)
        self.event1.quotas.create(name='Test quota')
        doc = self.get_doc('/control/event/%s/%s/live/' % (self.orga1.slug, self.event1.slug))
        assert len(doc.select(".btn-primary"))
        self.post_doc('/control/event/%s/%s/live/' % (self.orga1.slug, self.event1.slug),
                      {'live': 'true'})
        self.event1.refresh_from_db()
        assert self.event1.live

    def test_live_dont_require_payment_method_free(self):
        self.event1.items.create(name='Test', default_price=0)
        self.event1.settings.set('payment_banktransfer__enabled', False)
        self.event1.quotas.create(name='Test quota')
        doc = self.get_doc('/control/event/%s/%s/live/' % (self.orga1.slug, self.event1.slug))
        assert len(doc.select(".btn-primary"))

    def test_live_require_payment_method(self):
        self.event1.items.create(name='Test', default_price=5)
        self.event1.settings.set('payment_banktransfer__enabled', False)
        self.event1.quotas.create(name='Test quota')
        doc = self.get_doc('/control/event/%s/%s/live/' % (self.orga1.slug, self.event1.slug))
        assert len(doc.select(".btn-primary")) == 0

    def test_live_require_a_quota(self):
        self.event1.settings.set('payment_banktransfer__enabled', True)
        doc = self.get_doc('/control/event/%s/%s/live/' % (self.orga1.slug, self.event1.slug))
        assert len(doc.select(".btn-primary")) == 0

    def test_payment_settings(self):
        self.get_doc('/control/event/%s/%s/settings/payment' % (self.orga1.slug, self.event1.slug))
        self.post_doc('/control/event/%s/%s/settings/payment' % (self.orga1.slug, self.event1.slug), {
            'payment_banktransfer__enabled': 'true',
            'payment_banktransfer__fee_abs': '12.23',
            'payment_banktransfer_bank_details_0': 'Test',
            'settings-payment_term_days': '2',
            'settings-tax_rate_default': '19.00',
        })
        self.event1.settings._flush()
        assert self.event1.settings.get('payment_banktransfer__enabled', as_type=bool)
        assert self.event1.settings.get('payment_banktransfer__fee_abs', as_type=Decimal) == Decimal('12.23')

    def test_payment_settings_dont_require_fields_of_inactive_providers(self):
        doc = self.post_doc('/control/event/%s/%s/settings/payment' % (self.orga1.slug, self.event1.slug), {
            'settings-tax_rate_default': '19.00',
            'settings-payment_term_days': '2'
        }, follow=True)
        assert doc.select('.alert-success')

    def test_payment_settings_require_fields_of_active_providers(self):
        doc = self.post_doc('/control/event/%s/%s/settings/payment' % (self.orga1.slug, self.event1.slug), {
            'payment_banktransfer__enabled': 'true',
            'payment_banktransfer__fee_abs': '12.23',
            'settings-payment_term_days': '2',
            'settings-tax_rate_default': '19.00',
        })
        assert doc.select('.alert-danger')

    def test_invoice_settings(self):
        doc = self.get_doc('/control/event/%s/%s/settings/invoice' % (self.orga1.slug, self.event1.slug))
        data = extract_form_fields(doc.select("form")[0])
        data['invoice_address_required'] = 'on'
        doc = self.post_doc('/control/event/%s/%s/settings/invoice' % (self.orga1.slug, self.event1.slug),
                            data, follow=True)
        assert doc.select('.alert-success')
        self.event1.settings._flush()
        assert self.event1.settings.get('invoice_address_required', as_type=bool)

    def test_display_settings(self):
        with mocker_context() as mocker:
            mocked = mocker.patch('pretix.presale.style.regenerate_css.apply_async')

            doc = self.get_doc('/control/event/%s/%s/settings/display' % (self.orga1.slug, self.event1.slug))
            data = extract_form_fields(doc.select("form")[0])
            data['primary_color'] = '#FF0000'
            doc = self.post_doc('/control/event/%s/%s/settings/display' % (self.orga1.slug, self.event1.slug),
                                data, follow=True)
            assert doc.select('.alert-success')
            self.event1.settings._flush()
            assert self.event1.settings.get('primary_color') == '#FF0000'
            mocked.assert_any_call(args=(self.event1.pk,))

    def test_email_settings(self):
        with mocker_context() as mocker:
            mocked = mocker.patch('pretix.base.email.CustomSMTPBackend.test')

            doc = self.get_doc('/control/event/%s/%s/settings/email' % (self.orga1.slug, self.event1.slug))
            data = extract_form_fields(doc.select("form")[0])
            data['test'] = '1'
            doc = self.post_doc('/control/event/%s/%s/settings/email' % (self.orga1.slug, self.event1.slug),
                                data, follow=True)
            assert doc.select('.alert-success')
            self.event1.settings._flush()
            assert mocked.called

    def test_ticket_settings(self):
        doc = self.get_doc('/control/event/%s/%s/settings/tickets' % (self.orga1.slug, self.event1.slug))
        data = extract_form_fields(doc.select("form")[0])
        data['ticket_download'] = 'on'
        data['ticketoutput_testdummy__enabled'] = 'on'
        doc = self.post_doc('/control/event/%s/%s/settings/tickets' % (self.orga1.slug, self.event1.slug),
                            data, follow=True)
        self.event1.settings._flush()
        assert self.event1.settings.get('ticket_download', as_type=bool)
