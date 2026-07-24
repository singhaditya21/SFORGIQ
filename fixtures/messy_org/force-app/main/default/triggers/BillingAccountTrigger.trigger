trigger BillingAccountTrigger on Billing_Account__c (after insert, after update) {
    for (Billing_Account__c acct : Trigger.new) {
        List<Service_Order__c> orders = [SELECT Id FROM Service_Order__c WHERE Id = :acct.Id];
        Service_Order__c so = new Service_Order__c();
        insert so;
    }
}
