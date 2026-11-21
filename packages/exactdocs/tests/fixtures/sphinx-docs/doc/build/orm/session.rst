.. |store| replace:: ``Store``

.. _session_toplevel:

=============
Using a Store
=============

The |store| is where the ORM keeps objects between a query and a commit. See
:ref:`opening` before anything else, and :ref:`queryguide_toplevel` for queries.

.. index::
   single: Store

.. _opening:

Opening a Store
---------------

Create an :class:`acme.engine.Engine` and hand it to the :class:`~acme.orm.Store`::

    engine = create_engine("sqlite://")
    store = Store(engine)

Call :meth:`~.Store.flush` to send pending changes, :func:`acme.open_store` to open a
store with defaults and :attr:`.Store.autoflush` to switch flushing off. An
:term:`identity map` guarantees one object per row.

.. warning::

   Never share one ``Store`` between requests.

.. note::

   A store is cheap; open one per unit of work.

.. seealso::

   :doc:`../tutorial`

.. versionadded:: 2.1
   The ``retry_on`` option.

.. deprecated:: 2.0 Use :class:`.Store` instead.

Retry policies
~~~~~~~~~~~~~~

A store retries a failed flush when the error matches ``retry_on``:

.. code-block:: python+sql

   store = Store(engine, retry_on=(DeadlockError,))
   store.execute("SELECT * FROM orders")

Pass :paramref:`.Store.retry_on` to change it. Doctests work too:

>>> store.retry_on
(<class 'DeadlockError'>,)

Flush order
^^^^^^^^^^^

Objects flush in dependency order.

+---------+----------+-----------------+
| deletes | children | parents \| last |
+=========+==========+=================+
| first   | second   | third           |
+---------+----------+-----------------+

=====  =====  ==========
Phase  Order  Notes
=====  =====  ==========
one    1      inserts
two    2      updates
=====  =====  ==========

.. list-table:: Phases
   :header-rows: 1

   * - Phase
     - Order
     - Notes
   * - ``flush``
     - 1
     - writes

Including shared text
---------------------

.. include:: _inc/connection_note.rst

.. include:: ../../../outside/missing.rst

.. tab-set::

   .. tab-item:: Linux

      Use ``apt``.

Reference
---------

The unit of work, in full:

.. literalinclude:: examples/checkout.py
   :pyobject: open_and_add

The settings, by line:

.. literalinclude:: examples/settings.py
   :lines: 1-3
