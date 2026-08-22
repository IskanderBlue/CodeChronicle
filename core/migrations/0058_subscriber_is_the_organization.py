"""Move dj-stripe's subscriber from the person to the organization.

This is step 2 and step 3 of the card, and they cannot be separated: the
moment ``DJSTRIPE_SUBSCRIBER_MODEL`` becomes ``core.Organization``, every
``djstripe_customer.subscriber_id`` in the database means an organization, and
none of them holds one yet.

**Nothing is dropped.**  Each customer that names a person gets that person an
organization of one, with an ``admin`` membership, and the column is rewritten
to point at it.  The subscription, the invoices and the Stripe ids are
untouched.

Django will not generate this by itself, and it is worth knowing why.
dj-stripe declares the column as ``to=DJSTRIPE_SUBSCRIBER_MODEL``, read from
settings when the migration module is imported — so changing the setting
rewrites dj-stripe's recorded history rather than producing a change to
detect.  Model state and migration state agree, ``makemigrations`` reports
nothing, and the foreign key in the database goes on pointing at ``users``
until something moves it.  That something is this file.

Every step is written to be safe to run twice.
"""

from django.db import migrations

#: The table names, spelled once.
CUSTOMER = "djstripe_customer"
ORGANIZATIONS = "organizations"
MEMBERSHIPS = "organization_memberships"
USERS = "users"


def _subscriber_constraint(cursor) -> tuple[str, str] | None:
    """The foreign key on ``subscriber_id``, as (name, referenced table)."""
    cursor.execute(
        """
        SELECT con.conname, target.relname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_class target ON target.oid = con.confrelid
        JOIN pg_attribute att
          ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey)
        WHERE rel.relname = %s
          AND con.contype = 'f'
          AND att.attname = 'subscriber_id'
        """,
        [CUSTOMER],
    )
    row = cursor.fetchone()
    return (row[0], row[1]) if row else None


def move_subscriber_to_organization(apps, schema_editor):
    """Give every customer an organization, then repoint the foreign key."""
    with schema_editor.connection.cursor() as cursor:
        constraint = _subscriber_constraint(cursor)
        if constraint is not None and constraint[1] == ORGANIZATIONS:
            # A database built after the setting changed already has it right.
            return

        # Drop the old foreign key BEFORE any row changes, not after.
        #
        # Postgres queues a deferred trigger event for every row an UPDATE
        # touches while a DEFERRABLE key is in place, and it refuses to ALTER a
        # table that holds pending events:
        #
        #     cannot ALTER TABLE "djstripe_customer" because it has pending
        #     trigger events
        #
        # SET CONSTRAINTS ALL IMMEDIATE is not the answer either: it would run
        # the deferred checks against a column that already names an
        # organization while the key still names a user, so it fails instead.
        # The key cannot survive the rewrite in any order, so it goes first and
        # the rows change with no key in place.
        #
        # An empty table hides this, which is why the suite never saw it: with
        # no customer row there is no UPDATE and no pending event.
        if constraint is not None:
            cursor.execute(f'ALTER TABLE {CUSTOMER} DROP CONSTRAINT "{constraint[0]}"')

        # One organization for each person who has a Stripe customer, re-using
        # the one that is already there so a second run adds nothing.  A person
        # with a test-mode and a live-mode customer gets one organization, not
        # two: the organization is the firm, not the Stripe record.
        cursor.execute(
            f"""
            SELECT DISTINCT c.subscriber_id, u.email
            FROM {CUSTOMER} c
            JOIN {USERS} u ON u.id = c.subscriber_id
            WHERE c.subscriber_id IS NOT NULL
            """
        )
        subscribers = cursor.fetchall()

        for user_id, email in subscribers:
            cursor.execute(
                f"""
                SELECT m.organization_id
                FROM {MEMBERSHIPS} m
                WHERE m.user_id = %s AND m.role = 'admin'
                ORDER BY m.id
                LIMIT 1
                """,
                [user_id],
            )
            found = cursor.fetchone()
            if found:
                organization_id = found[0]
            else:
                cursor.execute(
                    f"""
                    INSERT INTO {ORGANIZATIONS} (name, email, created_at)
                    VALUES (%s, %s, NOW())
                    RETURNING id
                    """,
                    [email[:200], email],
                )
                organization_id = cursor.fetchone()[0]
                cursor.execute(
                    f"""
                    INSERT INTO {MEMBERSHIPS}
                        (organization_id, user_id, role, created_at)
                    VALUES (%s, %s, 'admin', NOW())
                    """,
                    [organization_id, user_id],
                )

            cursor.execute(
                f"UPDATE {CUSTOMER} SET subscriber_id = %s WHERE subscriber_id = %s",
                [organization_id, user_id],
            )

        # A customer whose subscriber names no live user cannot name an
        # organization either.  dj-stripe declares the column SET_NULL, so an
        # empty value is a state the product already handles.
        cursor.execute(
            f"""
            UPDATE {CUSTOMER} SET subscriber_id = NULL
            WHERE subscriber_id IS NOT NULL
              AND subscriber_id NOT IN (SELECT id FROM {ORGANIZATIONS})
            """
        )

        cursor.execute(
            f"""
            ALTER TABLE {CUSTOMER}
            ADD CONSTRAINT djstripe_customer_subscriber_id_fk_organizations_id
            FOREIGN KEY (subscriber_id) REFERENCES {ORGANIZATIONS} (id)
            DEFERRABLE INITIALLY DEFERRED
            """
        )


def restore_subscriber_to_user(apps, schema_editor):
    """Point the column back at the person who administers the organization.

    The reverse exists so a failed deploy can be rolled back on the same day.
    It leaves the organizations in place: they are real rows that people may
    already have joined, and deleting them to undo a foreign key would throw
    away seats.
    """
    with schema_editor.connection.cursor() as cursor:
        constraint = _subscriber_constraint(cursor)
        if constraint is not None and constraint[1] == USERS:
            return

        # Before any row changes, for the reason given in the forward.  A
        # rollback is the worst moment to meet the same fault twice.
        if constraint is not None:
            cursor.execute(f'ALTER TABLE {CUSTOMER} DROP CONSTRAINT "{constraint[0]}"')

        cursor.execute(
            f"""
            UPDATE {CUSTOMER} c
            SET subscriber_id = (
                SELECT m.user_id FROM {MEMBERSHIPS} m
                WHERE m.organization_id = c.subscriber_id AND m.role = 'admin'
                ORDER BY m.id LIMIT 1
            )
            WHERE c.subscriber_id IS NOT NULL
            """
        )
        cursor.execute(
            f"""
            UPDATE {CUSTOMER} SET subscriber_id = NULL
            WHERE subscriber_id IS NOT NULL
              AND subscriber_id NOT IN (SELECT id FROM {USERS})
            """
        )
        cursor.execute(
            f"""
            ALTER TABLE {CUSTOMER}
            ADD CONSTRAINT djstripe_customer_subscriber_id_fk_users_id
            FOREIGN KEY (subscriber_id) REFERENCES {USERS} (id)
            DEFERRABLE INITIALLY DEFERRED
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0057_organization_membership_invite"),
        # The table this rewrites belongs to dj-stripe, so dj-stripe must have
        # made it first.  With the setting changed, dj-stripe's own initial
        # migration already depends on 0057 above, so a fresh database orders
        # itself and this only has to say which table it comes after.
        ("djstripe", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            move_subscriber_to_organization,
            restore_subscriber_to_user,
        ),
    ]
