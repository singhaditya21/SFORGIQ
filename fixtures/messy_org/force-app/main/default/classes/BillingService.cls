public with sharing class BillingService {
    @InvocableMethod
    public static List<String> recalculate(List<Id> accountIds) {
        List<String> out = new List<String>();
        for (Id accountId : accountIds) {
            out.add(String.valueOf(accountId));
        }
        return out;
    }
}
