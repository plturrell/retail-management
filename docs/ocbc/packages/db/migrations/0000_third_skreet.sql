CREATE TABLE `bank_statements` (
	`statement_id` text PRIMARY KEY NOT NULL,
	`company_id` text NOT NULL,
	`bank_name` text NOT NULL,
	`account_number` text NOT NULL,
	`statement_date` text NOT NULL,
	`file_name` text NOT NULL,
	`file_hash` text NOT NULL,
	`imported_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`company_id`) REFERENCES `companies`(`company_id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `companies` (
	`company_id` text PRIMARY KEY NOT NULL,
	`uen` text NOT NULL,
	`name` text NOT NULL,
	`incorporation_date` text NOT NULL,
	`financial_year_start` text NOT NULL,
	`financial_year_end` text NOT NULL,
	`is_tax_resident` integer DEFAULT true NOT NULL,
	`shareholder_count` integer NOT NULL,
	`functional_currency` text DEFAULT 'SGD' NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `companies_uen_unique` ON `companies` (`uen`);--> statement-breakpoint
CREATE TABLE `financial_summaries` (
	`summary_id` text PRIMARY KEY NOT NULL,
	`company_id` text NOT NULL,
	`ya_year` integer NOT NULL,
	`total_revenue` real DEFAULT 0 NOT NULL,
	`total_expenses` real DEFAULT 0 NOT NULL,
	`net_profit_loss` real DEFAULT 0 NOT NULL,
	`adjusted_profit_loss` real DEFAULT 0 NOT NULL,
	`chargeable_income` real DEFAULT 0 NOT NULL,
	`tax_payable` real DEFAULT 0 NOT NULL,
	`exempt_amount` real DEFAULT 0 NOT NULL,
	`rebate_amount` real DEFAULT 0 NOT NULL,
	`status` text DEFAULT 'draft' NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`company_id`) REFERENCES `companies`(`company_id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `tax_adjustments` (
	`adjustment_id` text PRIMARY KEY NOT NULL,
	`summary_id` text NOT NULL,
	`description` text NOT NULL,
	`amount` real NOT NULL,
	`adjustment_type` text NOT NULL,
	`category` text DEFAULT 'other' NOT NULL,
	FOREIGN KEY (`summary_id`) REFERENCES `financial_summaries`(`summary_id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `transactions` (
	`transaction_id` text PRIMARY KEY NOT NULL,
	`statement_id` text NOT NULL,
	`company_id` text NOT NULL,
	`date` text NOT NULL,
	`description` text NOT NULL,
	`reference` text,
	`debit` real,
	`credit` real,
	`balance` real,
	`category` text DEFAULT 'other' NOT NULL,
	`subcategory` text,
	`is_taxable` integer DEFAULT true NOT NULL,
	`notes` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`statement_id`) REFERENCES `bank_statements`(`statement_id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`company_id`) REFERENCES `companies`(`company_id`) ON UPDATE no action ON DELETE cascade
);
