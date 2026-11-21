"""Open a store and add an order."""

from acme.orm import Store


def open_and_add(order):
    with Store.open() as store:
        store.add(order)
        store.commit()


def unrelated():
    return None
