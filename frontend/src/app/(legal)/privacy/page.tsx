import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy - AI Witness Organizer",
  description: "Privacy Policy for AI Witness Organizer by Juridion LLC",
};

const LAST_UPDATED = "2026-01-24";
const VERSION = "1.0";

export default function PrivacyPolicyPage() {
  return (
    <div>
      <h1 className="text-4xl font-bold mb-4">Privacy Policy</h1>
      <p className="text-muted-foreground mb-8">
        Last Updated: {LAST_UPDATED} | Version {VERSION}
      </p>

      {/* Table of Contents */}
      <nav className="bg-muted/50 rounded-lg p-6 mb-12">
        <h2 className="text-lg font-semibold mb-4">Table of Contents</h2>
        <ol className="list-decimal list-inside space-y-2 text-muted-foreground">
          <li><a href="#introduction" className="hover:text-foreground">Introduction</a></li>
          <li><a href="#information-we-collect" className="hover:text-foreground">Information We Collect</a></li>
          <li><a href="#how-we-use-information" className="hover:text-foreground">How We Use Your Information</a></li>
          <li><a href="#data-storage-security" className="hover:text-foreground">Data Storage and Security</a></li>
          <li><a href="#third-party-services" className="hover:text-foreground">Third-Party Services</a></li>
          <li><a href="#data-retention" className="hover:text-foreground">Data Retention</a></li>
          <li><a href="#your-rights" className="hover:text-foreground">Your Rights</a></li>
          <li><a href="#childrens-privacy" className="hover:text-foreground">Children&apos;s Privacy</a></li>
          <li><a href="#changes-to-policy" className="hover:text-foreground">Changes to This Policy</a></li>
          <li><a href="#contact-us" className="hover:text-foreground">Contact Us</a></li>
        </ol>
      </nav>

      {/* Section 1: Introduction */}
      <section id="introduction" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">1. Introduction</h2>
        <p className="mb-4">
          Juridion LLC (&quot;we,&quot; &quot;our,&quot; or &quot;us&quot;) operates AI Witness Organizer, an intelligent platform
          that helps legal professionals organize witness information and prepare for depositions.
          This Privacy Policy explains how we collect, use, disclose, and safeguard your information.
        </p>
        <p className="mb-4">
          By accessing or using AI Witness Organizer, you agree to this Privacy Policy. If you do not
          agree, please do not access the application.
        </p>
        <p>
          <strong>Company Information:</strong><br />
          Juridion LLC<br />
          Email: support@juridionllc.com
        </p>
      </section>

      {/* Section 2: Information We Collect */}
      <section id="information-we-collect" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">2. Information We Collect</h2>

        <h3 className="text-xl font-semibold mb-3">2.1 Account Information</h3>
        <p className="mb-4">When you create an account or authenticate through Clio, we collect:</p>
        <ul className="list-disc list-inside mb-6 space-y-2">
          <li>Your name and email address</li>
          <li>Law firm name and identifier</li>
          <li>Your role within the firm</li>
          <li>Clio user identification information</li>
        </ul>

        <h3 className="text-xl font-semibold mb-3">2.2 Clio Integration Data</h3>
        <p className="mb-4">Through our integration with Clio, we may access:</p>
        <ul className="list-disc list-inside mb-6 space-y-2">
          <li>Matter information (client names, matter numbers)</li>
          <li>Contact records related to matters</li>
          <li>User and attorney information within your firm</li>
        </ul>

        <h3 className="text-xl font-semibold mb-3">2.3 Witness Information</h3>
        <p className="mb-4">When you use the Service to organize witnesses, we process:</p>
        <ul className="list-disc list-inside mb-6 space-y-2">
          <li>Witness names and contact information</li>
          <li>Witness roles and relationships to cases</li>
          <li>Deposition schedules and status</li>
          <li>Notes and preparation materials</li>
          <li>Uploaded documents related to witnesses</li>
        </ul>

        <h3 className="text-xl font-semibold mb-3">2.4 Usage Data</h3>
        <p className="mb-4">We automatically collect:</p>
        <ul className="list-disc list-inside space-y-2">
          <li>Log data (IP address, browser type, pages visited)</li>
          <li>Feature usage patterns</li>
          <li>Error reports and performance data</li>
          <li>Device and connection information</li>
        </ul>
      </section>

      {/* Section 3: How We Use Your Information */}
      <section id="how-we-use-information" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">3. How We Use Your Information</h2>
        <p className="mb-4">We use the collected information to:</p>
        <ul className="list-disc list-inside space-y-2">
          <li>Provide and maintain the AI Witness Organizer service</li>
          <li>Organize and track witness information for your cases</li>
          <li>Generate deposition preparation materials</li>
          <li>Provide AI-powered insights and suggestions</li>
          <li>Synchronize with your Clio account</li>
          <li>Send service-related notifications</li>
          <li>Respond to support requests</li>
          <li>Improve our service</li>
          <li>Detect and prevent fraud or security issues</li>
          <li>Comply with legal obligations</li>
        </ul>
      </section>

      {/* Section 4: Data Storage and Security */}
      <section id="data-storage-security" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">4. Data Storage and Security</h2>

        <h3 className="text-xl font-semibold mb-3">4.1 Infrastructure</h3>
        <p className="mb-4">
          Your data is stored on Amazon Web Services (AWS) infrastructure in the United States.
          We utilize industry-standard security measures including:
        </p>
        <ul className="list-disc list-inside mb-6 space-y-2">
          <li>Encryption at rest using AES-256</li>
          <li>Encryption in transit using TLS 1.3</li>
          <li>Private network connections for AI processing</li>
          <li>Regular security audits</li>
          <li>Role-based access controls</li>
        </ul>

        <h3 className="text-xl font-semibold mb-3">4.2 Witness Data Protection</h3>
        <p className="mb-4">
          Witness information is stored securely and associated only with your firm&apos;s account.
          Access is restricted to authorized users within your organization.
        </p>

        <h3 className="text-xl font-semibold mb-3">4.3 Confidentiality</h3>
        <p>
          We understand the sensitive nature of witness information and case data. All data
          is treated as confidential and is not shared with other users or third parties
          except as necessary to provide the Service.
        </p>
      </section>

      {/* Section 5: Third-Party Services */}
      <section id="third-party-services" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">5. Third-Party Services</h2>
        <p className="mb-4">We use the following third-party services:</p>

        <h3 className="text-xl font-semibold mb-3">5.1 AWS Bedrock (AI Processing)</h3>
        <p className="mb-4">
          We use Amazon Bedrock with Claude AI models to provide intelligent features.
          Data is processed through secure AWS infrastructure.
        </p>

        <h3 className="text-xl font-semibold mb-3">5.2 Clio (Practice Management Integration)</h3>
        <p className="mb-4">
          We integrate with Clio for authentication and matter/contact management.
        </p>

        <h3 className="text-xl font-semibold mb-3">5.3 Stripe (Payment Processing)</h3>
        <p>
          We use Stripe for subscription payments. Payment details are handled directly by Stripe.
        </p>
      </section>

      {/* Section 6: Data Retention */}
      <section id="data-retention" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">6. Data Retention</h2>
        <p className="mb-4">We retain your data as follows:</p>
        <ul className="list-disc list-inside space-y-2">
          <li><strong>Active accounts:</strong> Data retained while subscription is active</li>
          <li><strong>Witness data:</strong> Retained for duration of subscription plus 30 days</li>
          <li><strong>After cancellation:</strong> Data retained for 30 days</li>
          <li><strong>Deletion request:</strong> Data deleted within 30 days of verified request</li>
        </ul>
      </section>

      {/* Section 7: Your Rights */}
      <section id="your-rights" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">7. Your Rights</h2>
        <p className="mb-4">You may have the following rights:</p>
        <ul className="list-disc list-inside mb-6 space-y-2">
          <li><strong>Access:</strong> Request a copy of your data</li>
          <li><strong>Correction:</strong> Request correction of inaccurate data</li>
          <li><strong>Deletion:</strong> Request deletion of your data</li>
          <li><strong>Data Portability:</strong> Export your witness data</li>
          <li><strong>Withdraw Consent:</strong> Disconnect your Clio account</li>
        </ul>
        <p>
          To exercise these rights, contact us at support@juridionllc.com.
        </p>
      </section>

      {/* Section 8: Children's Privacy */}
      <section id="childrens-privacy" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">8. Children&apos;s Privacy</h2>
        <p>
          AI Witness Organizer is designed for legal professionals. We do not knowingly
          collect information from individuals under 18.
        </p>
      </section>

      {/* Section 9: Changes to This Policy */}
      <section id="changes-to-policy" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">9. Changes to This Policy</h2>
        <p>
          We may update this Privacy Policy from time to time. We will notify you of material
          changes and update the &quot;Last Updated&quot; date.
        </p>
      </section>

      {/* Section 10: Contact Us */}
      <section id="contact-us" className="mb-12">
        <h2 className="text-2xl font-bold mb-4">10. Contact Us</h2>
        <div className="bg-muted/50 rounded-lg p-6">
          <p><strong>Juridion LLC</strong></p>
          <p>Email: support@juridionllc.com</p>
          <p>Subject Line: &quot;Privacy Inquiry - AI Witness Organizer&quot;</p>
        </div>
      </section>
    </div>
  );
}
