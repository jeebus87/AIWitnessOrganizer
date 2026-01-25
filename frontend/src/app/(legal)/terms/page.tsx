import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Service - AI Witness Organizer",
  description: "Terms of Service for AI Witness Organizer by Juridion LLC",
};

const LAST_UPDATED = "2026-01-24";
const VERSION = "1.0";

export default function TermsOfServicePage() {
  return (
    <div>
      <h1 className="text-4xl font-bold mb-4">Terms of Service</h1>
      <p className="text-muted-foreground mb-8">
        Last Updated: {LAST_UPDATED} | Version {VERSION}
      </p>

      {/* Table of Contents */}
      <nav className="bg-muted/50 rounded-lg p-6 mb-12">
        <h2 className="text-lg font-semibold mb-4">Table of Contents</h2>
        <ol className="list-decimal list-inside space-y-2 text-muted-foreground">
          <li><a href="#acceptance" className="hover:text-foreground">Acceptance of Terms</a></li>
          <li><a href="#description" className="hover:text-foreground">Description of Service</a></li>
          <li><a href="#accounts" className="hover:text-foreground">User Accounts and Responsibilities</a></li>
          <li><a href="#subscription" className="hover:text-foreground">Subscription and Billing</a></li>
          <li><a href="#clio-integration" className="hover:text-foreground">Clio Integration</a></li>
          <li><a href="#intellectual-property" className="hover:text-foreground">Intellectual Property</a></li>
          <li><a href="#ai-disclaimer" className="hover:text-foreground">AI-Generated Content Disclaimer</a></li>
          <li><a href="#limitation-liability" className="hover:text-foreground">Limitation of Liability</a></li>
          <li><a href="#indemnification" className="hover:text-foreground">Indemnification</a></li>
          <li><a href="#termination" className="hover:text-foreground">Termination</a></li>
          <li><a href="#governing-law" className="hover:text-foreground">Governing Law</a></li>
          <li><a href="#dispute-resolution" className="hover:text-foreground">Dispute Resolution</a></li>
          <li><a href="#contact" className="hover:text-foreground">Contact Information</a></li>
        </ol>
      </nav>

      {/* Section 1: Acceptance of Terms */}
      <section id="acceptance" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">1. Acceptance of Terms</h2>
        <p className="mb-4">
          These Terms of Service (&quot;Terms&quot;) constitute a legally binding agreement between you and
          Juridion LLC (&quot;Company,&quot; &quot;we,&quot; &quot;our,&quot; or &quot;us&quot;) governing your use of AI Witness Organizer
          (the &quot;Service&quot;).
        </p>
        <p className="mb-4">
          By accessing or using the Service, you agree to be bound by these Terms.
        </p>
        <p>
          If you are accepting on behalf of a law firm or legal entity, you represent that you have
          authority to bind that entity.
        </p>
      </section>

      {/* Section 2: Description of Service */}
      <section id="description" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">2. Description of Service</h2>
        <p className="mb-4">
          AI Witness Organizer is a software-as-a-service platform that provides:
        </p>
        <ul className="list-disc list-inside mb-4 space-y-2">
          <li>Witness information organization and management</li>
          <li>Deposition scheduling and tracking</li>
          <li>AI-powered deposition preparation assistance</li>
          <li>Witness relationship mapping</li>
          <li>Integration with Clio for matter and contact management</li>
          <li>Collaborative witness tracking for legal teams</li>
        </ul>
        <p>
          The Service is designed for use by legal professionals to organize witness information
          and prepare for litigation activities.
        </p>
      </section>

      {/* Section 3: User Accounts and Responsibilities */}
      <section id="accounts" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">3. User Accounts and Responsibilities</h2>

        <h3 className="text-xl font-semibold mb-3">3.1 Account Creation</h3>
        <p className="mb-4">
          To use the Service, you must create an account through Clio OAuth authentication.
        </p>

        <h3 className="text-xl font-semibold mb-3">3.2 Account Security</h3>
        <p className="mb-4">
          You are responsible for maintaining account confidentiality and all activities under your account.
        </p>

        <h3 className="text-xl font-semibold mb-3">3.3 Acceptable Use</h3>
        <p className="mb-4">You agree not to:</p>
        <ul className="list-disc list-inside space-y-2">
          <li>Use the Service for unlawful purposes</li>
          <li>Upload false or misleading witness information</li>
          <li>Share witness information inappropriately</li>
          <li>Attempt to circumvent security measures</li>
          <li>Reverse engineer the Service</li>
          <li>Resell access to the Service</li>
        </ul>
      </section>

      {/* Section 4: Subscription and Billing */}
      <section id="subscription" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">4. Subscription and Billing</h2>

        <h3 className="text-xl font-semibold mb-3">4.1 Subscription Plans</h3>
        <p className="mb-4">
          AI Witness Organizer is offered as a paid subscription. Pricing is available on our website.
        </p>

        <h3 className="text-xl font-semibold mb-3">4.2 Free Trial</h3>
        <p className="mb-4">
          New subscribers may be eligible for a free trial. Payment is charged when the trial ends
          unless cancelled.
        </p>

        <h3 className="text-xl font-semibold mb-3">4.3 Payment</h3>
        <p className="mb-4">
          Payments are processed through Stripe. Fees are non-refundable except as required by law.
        </p>

        <h3 className="text-xl font-semibold mb-3">4.4 Cancellation</h3>
        <p>
          You may cancel anytime. Access continues until end of billing period. Data retained 30 days.
        </p>
      </section>

      {/* Section 5: Clio Integration */}
      <section id="clio-integration" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">5. Clio Integration</h2>
        <p className="mb-4">
          AI Witness Organizer integrates with Clio for authentication and to sync matter and contact
          information. By using the Service, you authorize this integration.
        </p>
        <p>
          We are not responsible for Clio&apos;s availability or API changes.
        </p>
      </section>

      {/* Section 6: Intellectual Property */}
      <section id="intellectual-property" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">6. Intellectual Property</h2>

        <h3 className="text-xl font-semibold mb-3">6.1 Our Intellectual Property</h3>
        <p className="mb-4">
          The Service software and design are owned by Juridion LLC.
        </p>

        <h3 className="text-xl font-semibold mb-3">6.2 Your Data</h3>
        <p>
          You retain ownership of all witness information and data you input. You grant us a limited
          license to process your data solely for providing the Service.
        </p>
      </section>

      {/* Section 7: AI-Generated Content Disclaimer */}
      <section id="ai-disclaimer" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">7. AI-Generated Content Disclaimer</h2>
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-6 mb-4">
          <p className="font-semibold text-amber-400 mb-2">Important Notice:</p>
          <p className="text-amber-200">
            AI Witness Organizer provides AI-powered suggestions and insights. All AI-generated
            content should be verified by the user.
          </p>
        </div>

        <h3 className="text-xl font-semibold mb-3">7.1 Not Legal Advice</h3>
        <p className="mb-4">
          The Service does not provide legal advice. AI-generated suggestions for deposition
          preparation are for informational purposes only and must be reviewed by a licensed attorney.
        </p>

        <h3 className="text-xl font-semibold mb-3">7.2 User Verification Required</h3>
        <p className="mb-4">
          You are responsible for:
        </p>
        <ul className="list-disc list-inside mb-4 space-y-2">
          <li>Verifying accuracy of all witness information</li>
          <li>Reviewing AI-generated suggestions before use</li>
          <li>Ensuring compliance with discovery rules</li>
          <li>Maintaining appropriate witness contact protocols</li>
        </ul>

        <h3 className="text-xl font-semibold mb-3">7.3 No Attorney-Client Relationship</h3>
        <p>
          Use of the Service does not create an attorney-client relationship with Juridion LLC.
        </p>
      </section>

      {/* Section 8: Limitation of Liability */}
      <section id="limitation-liability" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">8. Limitation of Liability</h2>

        <h3 className="text-xl font-semibold mb-3">8.1 Disclaimer of Warranties</h3>
        <p className="mb-4 uppercase text-sm">
          THE SERVICE IS PROVIDED &quot;AS IS&quot; WITHOUT WARRANTIES OF ANY KIND.
        </p>

        <h3 className="text-xl font-semibold mb-3">8.2 Limitation of Damages</h3>
        <p className="mb-4 uppercase text-sm">
          JURIDION LLC SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, OR
          CONSEQUENTIAL DAMAGES.
        </p>

        <h3 className="text-xl font-semibold mb-3">8.3 Maximum Liability</h3>
        <p className="uppercase text-sm">
          OUR LIABILITY SHALL NOT EXCEED AMOUNTS PAID IN THE TWELVE (12) MONTHS PRECEDING THE CLAIM.
        </p>
      </section>

      {/* Section 9: Indemnification */}
      <section id="indemnification" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">9. Indemnification</h2>
        <p>
          You agree to indemnify Juridion LLC from claims arising from your use of the Service,
          witness information you manage, or your violation of these Terms.
        </p>
      </section>

      {/* Section 10: Termination */}
      <section id="termination" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">10. Termination</h2>
        <p className="mb-4">
          You may terminate your account anytime. We may suspend or terminate access for Terms
          violations or non-payment.
        </p>
        <p>
          Data is retained for 30 days after termination.
        </p>
      </section>

      {/* Section 11: Governing Law */}
      <section id="governing-law" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">11. Governing Law</h2>
        <p>
          These Terms are governed by Delaware law. Proceedings shall be in Delaware courts.
        </p>
      </section>

      {/* Section 12: Dispute Resolution */}
      <section id="dispute-resolution" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">12. Dispute Resolution</h2>
        <p className="mb-4">
          Before formal proceedings, contact us at support@juridionllc.com for informal resolution.
          Unresolved disputes go to binding arbitration.
        </p>
        <p>
          You waive class action rights.
        </p>
      </section>

      {/* Section 13: Contact Information */}
      <section id="contact" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">13. Contact Information</h2>
        <div className="bg-muted/50 rounded-lg p-6">
          <p><strong>Juridion LLC</strong></p>
          <p>Email: support@juridionllc.com</p>
          <p>Subject Line: &quot;Terms Inquiry - AI Witness Organizer&quot;</p>
        </div>
      </section>

      {/* Entire Agreement */}
      <section className="mb-12 border-t pt-8">
        <h2 className="text-2xl font-bold mb-4">Entire Agreement</h2>
        <p>
          These Terms, together with the Privacy Policy, constitute the entire agreement regarding
          AI Witness Organizer.
        </p>
      </section>
    </div>
  );
}
