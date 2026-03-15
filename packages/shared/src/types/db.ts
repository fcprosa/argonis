export interface BaseRecord {
  id:         string;
  created_at: string;
  updated_at: string;
}

export interface OwnedRecord extends BaseRecord {
  organization_id: string;
}
