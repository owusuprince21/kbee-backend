from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = "Create or refresh a confirmed TOTP device for a Django admin user."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Admin username to provision.")
        parser.add_argument("--name", default="default", help="Device name shown in admin.")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete existing devices with the same name for this user before creating a new one.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"]
        name = options["name"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(f"User '{username}' does not exist.") from exc

        if not user.is_staff:
            raise CommandError(f"User '{username}' is not staff and cannot access Django admin.")

        if options["replace"]:
            TOTPDevice.objects.filter(user=user, name=name).delete()

        device, created = TOTPDevice.objects.get_or_create(
            user=user,
            name=name,
            defaults={"confirmed": True},
        )
        if not device.confirmed:
            device.confirmed = True
            device.save(update_fields=["confirmed"])

        action = "Created" if created else "Using existing"
        self.stdout.write(self.style.SUCCESS(f"{action} TOTP device '{name}' for {username}."))
        self.stdout.write("Add this otpauth URL to Google Authenticator, 1Password, Authy, or similar:")
        self.stdout.write(device.config_url)
