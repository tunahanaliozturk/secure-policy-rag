---
id: DATA-004
title: Customer Data in Test Environments
department: data
classification: internal
---
# Customer Data in Test Environments

## 1. No production data by default
Production customer data may not be copied to development or test environments. Test environments use synthetic data or data masked by the approved masking tool.

## 2. Exceptions
An exception requires approval from the Data Protection Officer and the system owner, is valid for at most 30 days, and applies only to an environment with production-level access controls.

## 3. Masking rules
Masking must replace names, addresses, account numbers, national identification numbers and phone numbers. Masked data must not be reversible by the test team.
