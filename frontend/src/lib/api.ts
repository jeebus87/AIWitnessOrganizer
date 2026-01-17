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

  async processMatter(id: number, token: string, options?: ProcessMatterOptions) {
    return this.request<ProcessingJob>(`/api/v1/matters/${id}/process`, {
      method: "POST",
      token,
      body: options || {},
    });
  }

  async getMatterFolders(matterId: number, token: string) {
    return this.request<FolderTreeResponse>(`/api/v1/matters/${matterId}/folders`, { token });
  }

  // Witnesses
  async getWitnesses(token: string, params?: WitnessFilters) {
    const query = params ? "?" + new URLSearchParams(params as Record<string, string>).toString() : "";
    return this.request<WitnessListResponse>(`/api/v1/witnesses${query}`, { token });
  }

  // Jobs
  async getJobs(token: string) {
    return this.request<JobListResponse>("/api/v1/jobs", { token });
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
  user_id: number;
  celery_task_id: string;
  job_type: string;
  target_matter_id: number;
  status: JobStatus;
  total_documents: number;
  processed_documents: number;
  failed_documents: number;
  total_witnesses_found: number;
  error_message: string;
  started_at: string;
  completed_at: string;
  created_at: string;
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

export interface ProcessMatterOptions {
  scan_folder_id?: number | null;
  legal_authority_folder_id?: number | null;
  include_subfolders?: boolean;
}

export const api = new ApiClient(API_BASE_URL);
