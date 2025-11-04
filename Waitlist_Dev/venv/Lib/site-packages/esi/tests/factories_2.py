"""Factories for test objects using factory boy."""

import factory
import factory.fuzzy

from esi.models import Token, Scope, CallbackRedirect


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "auth.User"
        django_get_or_create = ("username",)
        exclude = ("_generated_name",)

    _generated_name = factory.Faker("name")
    username = factory.LazyAttribute(lambda obj: obj._generated_name.replace(" ", "_"))
    first_name = factory.LazyAttribute(lambda obj: obj._generated_name.split(" ")[0])
    last_name = factory.LazyAttribute(lambda obj: obj._generated_name.split(" ")[1])
    email = factory.LazyAttribute(
        lambda obj: f"{obj.first_name.lower()}.{obj.last_name.lower()}@example.com"
    )


class TokenFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Token

    access_token = factory.faker.Faker("pystr", min_chars=2_507, max_chars=2_507)
    refresh_token = factory.faker.Faker("pystr", min_chars=24, max_chars=24)
    user = factory.SubFactory(UserFactory)
    character_id = factory.fuzzy.FuzzyInteger(low=90_000_000, high=98_000_000)
    character_name = factory.faker.Faker("name")
    token_type = "Character"
    character_owner_hash = factory.faker.Faker("pystr", min_chars=28, max_chars=28)
    sso_version = 2

    @factory.post_generation
    def scopes(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            for scope in extracted:
                self.scopes.add(scope)


class ScopeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Scope

    name = factory.faker.Faker("word")
    help_text = factory.faker.Faker("sentence")


class CallbackRedirectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CallbackRedirect

    session_key = factory.faker.Faker("md5")
    url = factory.faker.Faker("uri_path", deep=3)
    state = factory.faker.Faker("sha1")
