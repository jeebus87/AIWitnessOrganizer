const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ApiOptions {
  method?: string;
  body?: unknown;
  token?: string;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(endpoint: string, options: ApiOptions = {}): Promise<T> {
    const { method = "GET", body, token } = options;

    const headers: HeadersInit = {
      "Content-Type": "application/json",
    };

    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(error.detail || `API error: ${response.status}`);
    }

    return response.json();
  }

  // Health check
  async health() {
    return this.request<{ status: string; version: string; environment: string }>("/health");
  }

  // Auth
  getLoginUrl() {
    return `${this.baseUrl}/api/v1/auth/clio`;
  }

  // Matters
  async getMatters(token: string, params: GetMattersParams = {}) {
    const searchParams = new URLSearchParams();
    if (params.page) searchParams.set('page', params.page.toString());
    if (params.pageSize) searchParams.set('page_size', params.pageSize.toString());
    if (params.sortBy) searchParams.set('sort_by', params.sortBy);
    if (params.sortOrder) searchParams.set('sort_order', params.sortOrder);
    if (params.search) searchParams.set('search', params.search);
    if (params.status) searchParams.set('status', params.status);
    if (params.practiceArea) searchParams.set('practice_area', params.practiceArea);
    if (params.clientName) searchParams.set('client_name', params.clientName);
    if (params.syncedAfter) searchParams.set('synced_after', params.syncedAfter);
    if (params.syncedBefore) searchParams.set('synced_before', params.syncedBefore);
    const query = searchParams.toString();
    return this.request<MatterListResponse>(`/api/v1/matters${query ? '?' + query : ''}`, { token });
  }

  async getMatterFilters(token: string) {
    return this.request<MatterFilters>("/api/v1/matters/filters", { token });
  }

  async getMatter(id: number, token: string) {
    return this.request<Matter>(`/api/v1/matters/${id}`, { token });
  }

  async syncMatters(token: string, clearExisting: boolean = false) {
    const params = clearExisting ? "?clear_existing=true" : "";
    return this.request<{ success: boolean; matters_synced: number }>(`/api/v1/matters/sync${params}`, {
      method: "POST",
      token,
    });
  }

  // Sync documents for all matters (background task)
  async syncAllDocuments(token: string) {
    return this.request<{ success: boolean; message: string; task_id: string }>("/api/v1/matters/sync-all", {
      method: "POST",
      token,
    });
  }

  // Sync documents for a specific matter
  async syncMatterDocuments(token: string, matterId: number) {
    return this.request<{ success: boolean; message: string; task_id: string }>(`/api/v1/matters/${matterId}/sync`, {
      method: "POST",
      token,
    });
  }

  // Get current sync status for the user
  async getSyncStatus(token: string) {
    return this.request<{ is_syncing: boolean; syncing_count: number; recovered_stale_count: number }>("/api/v1/matters/sync-status", {
      token,
    });
  }

  // Disconnect Clio integration (for reauthorization)
  async disconnectClio(token: string) {
    return this.request<{ success: boolean; message: string }>("/api/v1/auth/clio/disconnect", {
      method: "POST",
      token,
    });
  }

  async processMatter(id: number, token: string, options?: ProcessMatterOptions): Promise<ProcessMatterResponse> {
    const response = await fetch(`${this.baseUrl}/api/v1/matters/${id}/process`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`,
      },
      body: JSON.stringify(options || {}),
    });

    const data = await response.json();

    if (!response.ok && response.status !== 202) {
      throw new Error(data.detail || `API error: ${response.status}`);
    }

    // Check if this is a syncing response (202) or a job response (200)
    if (response.status === 202 || data.status === "syncing") {
      return { status: "syncing", message: data.message, task_id: data.task_id };
    }

    return { status: "processing", job: data as ProcessingJob };
  }

  async getMatterFolders(matterId: number, token: string) {
    return this.request<FolderTreeResponse>(`/api/v1/matters/${matterId}/folders`, { token });
  }

  // Get document count for a matter (optionally filtered by folder)
  async getDocumentCount(matterId: number, token: string, folderId?: string | null, includeSubfolders: boolean = false) {
    const queryParams = new URLSearchParams();
    if (folderId) queryParams.set("folder_id", folderId);
    queryParams.set("include_subfolders", includeSubfolders.toString());
    const params = queryParams.toString() ? `?${queryParams.toString()}` : "";
    return this.request<DocumentCountResponse>(`/api/v1/matters/${matterId}/documents/count${params}`, { token });
  }

  // Witnesses
  async getWitnesses(token: string, params?: WitnessFilters) {
    const query = params ? "?" + new URLSearchParams(params as Record<string, string>).toString() : "";
    return this.request<WitnessListResponse>(`/api/v1/witnesses${query}`, { token });
  }

  // Canonical (deduplicated) witnesses
  async getCanonicalWitnesses(token: string, params?: CanonicalWitnessFilters) {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set('page', params.page.toString());
    if (params?.page_size) searchParams.set('page_size', params.page_size.toString());
    if (params?.matter_id) searchParams.set('matter_id', params.matter_id.toString());
    if (params?.relevance) searchParams.set('relevance', params.relevance);
    if (params?.role) searchParams.set('role', params.role);
    if (params?.search) searchParams.set('search', params.search);
    const query = searchParams.toString();
    return this.request<CanonicalWitnessListResponse>(`/api/v1/witnesses/canonical${query ? '?' + query : ''}`, { token });
  }

  // Jobs
  async getJobs(token: string, archived: boolean = false) {
    const params = new URLSearchParams();
    if (archived) params.set('archived', 'true');
    const query = params.toString();
    return this.request<JobListResponse>(`/api/v1/jobs${query ? '?' + query : ''}`, { token });
  }

  async getJobStats(token: string) {
    return this.request<JobStats>("/api/v1/jobs/stats/counts", { token });
  }

  async getJob(id: number, token: string) {
    return this.request<ProcessingJob>(`/api/v1/jobs/${id}`, { token });
  }

  async cancelJob(id: number, token: string) {
    return this.request<{ success: boolean }>(`/api/v1/jobs/${id}/cancel`, {
      method: "POST",
      token,
    });
  }

  async archiveJob(id: number, token: string) {
    return this.request<{ success: boolean }>(`/api/v1/jobs/${id}/archive`, {
      method: "POST",
      token,
    });
  }

  async unarchiveJob(id: number, token: string) {
    return this.request<{ success: boolean }>(`/api/v1/jobs/${id}/unarchive`, {
      method: "POST",
      token,
    });
  }

  async deleteJob(id: number, token: string) {
    return this.request<{ success: boolean }>(`/api/v1/jobs/${id}`, {
      method: "DELETE",
      token,
    });
  }

  async clearFinishedJobs(token: string) {
    return this.request<{ success: boolean; deleted_count: number }>("/api/v1/jobs", {
      method: "DELETE",
      token,
    });
  }

  // Exports
  getExportPdfUrl(jobId: number) {
    return `${this.baseUrl}/api/v1/jobs/${jobId}/export/pdf`;
  }

  getExportExcelUrl(jobId: number) {
    return `${this.baseUrl}/api/v1/jobs/${jobId}/export/excel`;
  }

  getExportDocxUrl(jobId: number) {
    return `${this.baseUrl}/api/v1/jobs/${jobId}/export/docx`;
  }

  // User
  async getCurrentUser(token: string) {
    return this.request<UserProfile>("/api/v1/auth/me", { token });
  }
  // Billing
  async createCheckoutSession(token: string, priceId: string) {
    const params = new URLSearchParams({ price_id: priceId });
    return this.request<{ url: string }>(`/api/v1/billing/create-checkout-session?${params}`, {
      method: "POST",
      token,
    });
  }

  async createPortalSession(token: string) {
    return this.request<{ url: string }>("/api/v1/billing/portal", {
      method: "POST",
      token,
    });
  }

  async createSubscriptionCheckout(token: string, userCount: number = 1) {
    return this.request<{ url: string }>("/api/v1/billing/checkout", {
      method: "POST",
      token,
      body: { user_count: userCount },
    });
  }

  async createTopupCheckout(token: string, packageId: string) {
    return this.request<{ url: string }>("/api/v1/billing/credits/topup", {
      method: "POST",
      token,
      body: { package: packageId },
    });
  }

  async getCredits(token: string) {
    return this.request<CreditInfo>("/api/v1/billing/credits", { token });
  }

  async getSubscriptionStatus(token: string) {
    return this.request<SubscriptionStatus>("/api/v1/billing/status", { token });
  }

  async updateOrganizationName(token: string, name: string) {
    return this.request<{ id: number; name: string; updated: boolean }>("/api/v1/billing/organization/name", {
      method: "PUT",
      token,
      body: { name },
    });
  }

  // Relevancy
  async getRelevancy(matterId: number, token: string) {
    return this.request<RelevancyAnalysis>(`/api/v1/relevancy/${matterId}`, { token });
  }

  async getClaims(matterId: number, token: string) {
    return this.request<CaseClaim[]>(`/api/v1/relevancy/${matterId}/claims`, { token });
  }

  async addClaim(matterId: number, token: string, claim: CreateClaimRequest) {
    return this.request<CaseClaim>(`/api/v1/relevancy/${matterId}/claims`, {
      method: "POST",
      token,
      body: claim,
    });
  }

  async updateClaim(matterId: number, claimId: number, token: string, updates: UpdateClaimRequest) {
    return this.request<CaseClaim>(`/api/v1/relevancy/${matterId}/claims/${claimId}`, {
      method: "PUT",
      token,
      body: updates,
    });
  }

  async deleteClaim(matterId: number, claimId: number, token: string) {
    return this.request<{ success: boolean }>(`/api/v1/relevancy/${matterId}/claims/${claimId}`, {
      method: "DELETE",
      token,
    });
  }

  async linkWitnessToClaim(matterId: number, token: string, link: CreateWitnessLinkRequest) {
    return this.request<WitnessClaimLink>(`/api/v1/relevancy/${matterId}/witness-links`, {
      method: "POST",
      token,
      body: link,
    });
  }

  // Legal Research
  async getLegalResearchForJob(jobId: number, token: string) {
    return this.request<LegalResearchResponse>(`/api/v1/legal-research/job/${jobId}`, { token });
  }

  async approveLegalResearch(researchId: number, token: string, selectedCaseIds: number[]) {
    return this.request<{ status: string; message: string; research_id: number }>(
      `/api/v1/legal-research/${researchId}/approve`,
      {
        method: "POST",
        token,
        body: { selected_case_ids: selectedCaseIds },
      }
    );
  }

  async dismissLegalResearch(researchId: number, token: string) {
    return this.request<{ status: string; message: string; research_id: number }>(
      `/api/v1/legal-research/${researchId}/dismiss`,
      {
        method: "POST",
        token,
      }
    );
  }

  async getPendingLegalResearch(token: string) {
    return this.request<PendingLegalResearchResponse>("/api/v1/legal-research/pending", { token });
  }
}

// Types
export interface Matter {
  id: number;
  clio_matter_id: string;
  display_number: string;
  description: string;
  status: string;
  practice_area: string;
  client_name: string;
  last_synced_at: string;
  created_at: string;
}

export interface Witness {
  id: number;
  document_id: number;
  full_name: string;
  role: WitnessRole;
  importance: ImportanceLevel;
  observation: string;
  source_quote: string;
  context: string;
  email: string;
  phone: string;
  address: string;
  confidence_score: number;
  created_at: string;
}

export type WitnessRole =
  | "plaintiff"
  | "defendant"
  | "eyewitness"
  | "expert"
  | "attorney"
  | "physician"
  | "police_officer"
  | "family_member"
  | "colleague"
  | "bystander"
  | "mentioned"
  | "other";

export type ImportanceLevel = "high" | "medium" | "low";

export type JobStatus = "pending" | "processing" | "completed" | "failed" | "cancelled";

export interface ProcessingJob {
  id: number;
  job_number: number | null;  // Sequential job number per organization
  user_id: number;
  celery_task_id: string;
  job_type: string;
  target_matter_id: number;
  matter_name: string | null;  // Formatted: "Case Caption, Case No. 12345"
  status: JobStatus;
  total_documents: number;
  processed_documents: number;
  failed_documents: number;
  total_witnesses_found: number;
  error_message: string;
  started_at: string;
  completed_at: string;
  created_at: string;
  is_archived: boolean;
  archived_at: string | null;
}

export interface JobStats {
  total: number;
  completed: number;
  processing: number;
  pending: number;
  failed: number;
  archived: number;
}

export interface WitnessFilters {
  matter_id?: string;
  role?: WitnessRole;
  importance?: ImportanceLevel;
  search?: string;
}

export interface Organization {
  id: number;
  name: string;
  subscription_status: string;
  subscription_tier: string;
  user_count: number;
  bonus_credits: number;
  current_period_end: string | null;
}

export interface UserProfile {
  id: number;
  email: string;
  display_name: string;
  subscription_tier: string;
  is_admin: boolean;
  clio_connected: boolean;
  created_at: string;
  organization: Organization | null;
}

export interface CreditInfo {
  daily_remaining: number;
  bonus_remaining: number;
  is_paid: boolean;
  unlimited: boolean;
}

export interface SubscriptionStatus {
  status: string;
  tier: string;
  is_admin: boolean;
  user_count: number;
  organization_name: string | null;
  current_period_end: string | null;
  bonus_credits: number;
}

// Paginated response types
export interface MatterListResponse {
  matters: Matter[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface GetMattersParams {
  page?: number;
  pageSize?: number;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  search?: string;
  status?: string;
  practiceArea?: string;
  clientName?: string;
  syncedAfter?: string;
  syncedBefore?: string;
}

export interface MatterFilters {
  statuses: string[];
  practice_areas: string[];
  clients: string[];
}

export interface WitnessListResponse {
  witnesses: Witness[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// Canonical (deduplicated) witness types
export interface CanonicalObservation {
  document_id: number;
  document_filename: string;
  page: number | null;
  text: string;
}

export interface CanonicalWitness {
  id: number;
  matter_id: number;
  full_name: string;
  role: WitnessRole;
  relevance: string | null;
  relevance_reason: string | null;
  observations: CanonicalObservation[];
  email: string | null;
  phone: string | null;
  address: string | null;
  source_document_count: number;
  max_confidence_score: number | null;
  created_at: string;
  updated_at: string;
}

export interface CanonicalWitnessListResponse {
  witnesses: CanonicalWitness[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface CanonicalWitnessFilters {
  page?: number;
  page_size?: number;
  matter_id?: number;
  relevance?: string;
  role?: string;
  search?: string;
}

export interface JobListResponse {
  jobs: ProcessingJob[];
  total: number;
}

export interface Folder {
  id: number;
  name: string;
  parent_id: number | null;
  children: Folder[];
}

export interface FolderTreeResponse {
  folders: Folder[];
}

export interface DocumentCountResponse {
  count: number;
  folder_id: string | null;
  matter_id: number;
  sync_status: string;
  last_synced_at: string | null;
}

export interface ProcessMatterOptions {
  scan_folder_id?: number | null;
  legal_authority_folder_id?: number | null;
  include_subfolders?: boolean;
}

// Process matter response - can be syncing or processing
export type ProcessMatterResponse =
  | { status: "syncing"; message: string; task_id: string }
  | { status: "processing"; job: ProcessingJob };

// Relevancy types
export type ClaimType = "allegation" | "defense";

export interface CaseClaim {
  id: number;
  matter_id: number;
  claim_type: ClaimType;
  claim_number: number;
  claim_text: string;
  source_document_id: number | null;
  source_page: number | null;
  extraction_method: string;
  confidence_score: number | null;
  is_verified: boolean;
  created_at: string;
  updated_at: string;
  linked_witnesses?: WitnessClaimLink[];
}

export interface WitnessClaimLink {
  id: number;
  witness_id: number;
  case_claim_id: number;
  witness_name?: string;
  relevance_explanation: string | null;
  supports_or_undermines: "supports" | "undermines" | "neutral";
  created_at: string;
}

export interface RelevancyAnalysis {
  matter_id: number;
  allegations: CaseClaimWithWitnesses[];
  defenses: CaseClaimWithWitnesses[];
  witness_summary: WitnessSummary[];
  unlinked_witnesses: UnlinkedWitness[];
}

export interface CaseClaimWithWitnesses extends Omit<CaseClaim, 'linked_witnesses'> {
  linked_witnesses: {
    witness_id: number;
    witness_name: string;
    relationship: "supports" | "undermines" | "neutral";
    explanation: string | null;
  }[];
}

export interface WitnessSummary {
  witness_id: number;
  name: string;
  claim_links: {
    claim_id: number;
    claim_type: ClaimType;
    claim_number: number;
    relationship: "supports" | "undermines" | "neutral";
    explanation: string | null;
  }[];
}

export interface UnlinkedWitness {
  id: number;
  full_name: string;
  role: WitnessRole;
}

export interface CreateClaimRequest {
  claim_type: ClaimType;
  claim_text: string;
  source_document_id?: number | null;
  source_page?: number | null;
  extraction_method?: string;
}

export interface UpdateClaimRequest {
  claim_text?: string;
  is_verified?: boolean;
}

export interface CreateWitnessLinkRequest {
  witness_id: number;
  case_claim_id: number;
  relevance_explanation?: string;
  supports_or_undermines?: "supports" | "undermines" | "neutral";
}

// Legal Research types
export interface CaseLawResult {
  id: number;
  case_name: string;
  citation: string | null;
  court: string;
  date_filed: string | null;
  snippet: string;
  absolute_url: string;
  pdf_url: string | null;
  relevance_score: number;
}

export interface LegalResearchResponse {
  has_results: boolean;
  id?: number;
  job_id?: number;
  status?: string;
  results?: CaseLawResult[];
  selected_ids?: number[];
  created_at?: string;
}

export interface PendingLegalResearchItem {
  id: number;
  job_id: number;
  matter_id: number;
  result_count: number;
  created_at: string | null;
}

export interface PendingLegalResearchResponse {
  pending_count: number;
  items: PendingLegalResearchItem[];
}

export const api = new ApiClient(API_BASE_URL);
