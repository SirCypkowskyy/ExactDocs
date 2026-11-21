========
Tutorial
========

This tutorial writes a first scenario in Gherkin and runs it. Before you begin,
:doc:`install the runner <index>` from :pypi:`acme-runner`.

Writing a scenario
==================

Save the following as ``checkout.feature``:

.. code-block:: gherkin

   Feature: checkout
     Scenario: a customer pays
       Given a cart with one item
       When the customer pays
       Then the order is complete

Every step starts with one of these words:

Given
    Put the system in a known state.

When
    Describe the action under test.

Then
    Observe the outcome.

Running it
==========

#. Open a terminal in the project folder.
#. Run ``acme-runner checkout.feature``.
#. Read the report.
