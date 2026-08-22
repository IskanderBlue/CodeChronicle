"""Drop the second copy of the Stripe customer id.

``dj-stripe`` mirrors the customer, and ``Customer.subscriber`` names the
organization the person belongs to.  That is the one link.  The column on
``users`` was a shortcut for a lookup that now has an owner, and a second copy
can disagree with the first.

Checked before removal: production held one non-empty value, and it was equal
to the mirrored ``Customer.id`` reached through the person's organization.  The
column carried nothing the models do not.

**A dropped column has a hazard an added one does not.**  The deploy applies
migrations before it replaces the container, so between the two the previous
image still names this column in its ``User`` model and any ``SELECT`` against
``users`` fails.  Anonymous traffic does not reach that query — the
authentication middleware reads ``users`` only when a session cookie is present
— so the exposure is a signed-in request inside a window of seconds.  With six
accounts that is accepted rather than engineered around.  A table people
actually sign in to needs the two-deploy form instead: remove the field from
Django state first, drop the column in the release after.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0059_api_throttle_event"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="stripe_customer_id",
        ),
    ]
