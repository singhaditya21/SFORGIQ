trigger BillingAccountAuditTrigger on Billing_Account__c (before update) {
    System.debug('audit');
}
