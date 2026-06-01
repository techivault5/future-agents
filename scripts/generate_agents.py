#!/usr/bin/env python3
"""
IT Agents Generator
Generates 10,000 agent type definitions across technical and non-technical IT roles.
"""

import itertools
import json
from pathlib import Path

import yaml

# ─────────────────────────────────────────────
# BASE DATA
# ─────────────────────────────────────────────

SENIORITY_LEVELS = [
    "intern",
    "junior",
    "mid",
    "senior",
    "lead",
    "principal",
    "staff",
    "architect",
    "distinguished",
    "fellow",
]

INDUSTRIES = [
    "fintech",
    "healthtech",
    "edtech",
    "govtech",
    "retailtech",
    "legaltech",
    "insurtech",
    "proptech",
    "agrotech",
    "cleantech",
    "cybersecurity",
    "defense",
    "media",
    "telecom",
    "logistics",
    "automotive",
    "aerospace",
    "pharma",
    "gaming",
    "saas",
]

METHODOLOGIES = [
    "agile",
    "scrum",
    "kanban",
    "lean",
    "devops",
    "sre",
    "devsecops",
    "gitops",
    "platform-engineering",
    "shift-left",
    "chaos-engineering",
]

CLOUD_PROVIDERS = ["aws", "azure", "gcp", "multi-cloud", "hybrid-cloud", "on-prem"]

TECH_ROLE_CATEGORIES = {
    "frontend-development": {
        "description": "Build user-facing web interfaces and experiences",
        "tech_stacks": [
            "react",
            "vue",
            "angular",
            "svelte",
            "nextjs",
            "nuxt",
            "astro",
            "vanilla-js",
            "typescript",
            "webcomponents",
            "lit",
            "qwik",
            "remix",
            "solidjs",
            "htmx",
            "tailwindcss",
            "css-in-js",
        ],
        "skills": [
            "ui-design",
            "accessibility",
            "performance",
            "seo",
            "pwa",
            "micro-frontends",
            "design-systems",
            "testing",
            "state-management",
            "graphql-client",
            "websockets",
            "webgl",
            "wasm",
        ],
        "tools": ["webpack", "vite", "storybook", "playwright", "cypress", "jest", "vitest"],
        "certifications": ["google-ux", "aws-clf", "meta-frontend"],
    },
    "backend-development": {
        "description": "Design and build server-side applications and APIs",
        "tech_stacks": [
            "nodejs",
            "python-fastapi",
            "python-django",
            "java-spring",
            "go",
            "rust",
            "ruby-on-rails",
            "php-laravel",
            "dotnet",
            "kotlin-ktor",
            "elixir-phoenix",
            "haskell",
            "scala-play",
            "clojure",
            "erlang",
        ],
        "skills": [
            "rest-api",
            "graphql",
            "grpc",
            "microservices",
            "monolith",
            "event-driven",
            "cqrs",
            "ddd",
            "hexagonal-arch",
            "auth-authz",
            "rate-limiting",
            "caching",
            "message-queues",
            "background-jobs",
        ],
        "tools": ["docker", "kubernetes", "redis", "rabbitmq", "kafka", "elasticsearch"],
        "certifications": ["aws-dva", "cka", "oracle-java"],
    },
    "fullstack-development": {
        "description": "Build complete end-to-end applications across frontend and backend",
        "tech_stacks": [
            "nextjs-node",
            "nuxt-node",
            "remix-node",
            "sveltekit",
            "t3-stack",
            "blitzjs",
            "redwoodjs",
            "nestjs-react",
            "django-react",
            "rails-react",
            "laravel-vue",
            "spring-react",
        ],
        "skills": [
            "full-sdlc",
            "database-design",
            "api-design",
            "ui-ux",
            "deployment",
            "monitoring",
            "ci-cd",
            "testing-full-stack",
        ],
        "tools": ["monorepo-tools", "nx", "turborepo", "lerna"],
        "certifications": ["aws-saa", "gcp-ace"],
    },
    "mobile-development": {
        "description": "Build native and cross-platform mobile applications",
        "tech_stacks": [
            "ios-swift",
            "ios-objc",
            "android-kotlin",
            "android-java",
            "react-native",
            "flutter",
            "xamarin",
            "ionic",
            "capacitor",
            "expo",
            "kotlin-multiplatform",
            "swift-ui",
            "jetpack-compose",
        ],
        "skills": [
            "app-store-optimization",
            "push-notifications",
            "offline-first",
            "biometrics",
            "camera-apis",
            "gps-location",
            "bluetooth",
            "in-app-purchases",
            "ar-mobile",
            "deep-linking",
            "accessibility",
        ],
        "tools": ["xcode", "android-studio", "fastlane", "firebase", "testflight"],
        "certifications": ["google-android", "apple-developer"],
    },
    "devops-engineering": {
        "description": "Enable continuous delivery and operational excellence",
        "tech_stacks": [
            "jenkins",
            "github-actions",
            "gitlab-ci",
            "circleci",
            "azure-devops",
            "argocd",
            "tekton",
            "flux",
            "spinnaker",
            "harness",
            "drone-ci",
            "bamboo",
        ],
        "skills": [
            "ci-cd",
            "infrastructure-as-code",
            "gitops",
            "release-management",
            "pipeline-design",
            "artifact-management",
            "environment-management",
            "shift-left-testing",
            "feature-flags",
            "blue-green",
            "canary",
        ],
        "tools": ["terraform", "ansible", "packer", "vagrant", "helm", "kustomize"],
        "certifications": ["cka", "ckad", "aws-devops-pro", "dod"],
    },
    "platform-engineering": {
        "description": "Build internal developer platforms and golden paths",
        "tech_stacks": ["backstage", "port", "cortex", "configure8", "kubernetes", "crossplane", "pulumi", "terraform"],
        "skills": [
            "idp-design",
            "developer-experience",
            "self-service-infra",
            "golden-paths",
            "platform-apis",
            "service-catalog",
            "cost-optimization",
            "capacity-planning",
        ],
        "tools": ["backstage", "argocd", "vault", "consul", "boundary"],
        "certifications": ["cka", "ckad", "cks", "aws-sap"],
    },
    "sre-engineering": {
        "description": "Ensure reliability, scalability and performance of production systems",
        "tech_stacks": [
            "prometheus",
            "grafana",
            "datadog",
            "newrelic",
            "dynatrace",
            "honeycomb",
            "lightstep",
            "jaeger",
            "zipkin",
            "opentelemetry",
        ],
        "skills": [
            "slo-sla-sli",
            "incident-management",
            "chaos-engineering",
            "capacity-planning",
            "on-call-management",
            "post-mortem",
            "toil-reduction",
            "observability",
            "tracing",
            "alerting",
        ],
        "tools": ["pagerduty", "opsgenie", "statuspage", "runbooks", "gamechanger"],
        "certifications": ["google-sre", "aws-sap", "cka"],
    },
    "cloud-architecture": {
        "description": "Design scalable, secure, and cost-efficient cloud solutions",
        "tech_stacks": [
            "aws",
            "azure",
            "gcp",
            "alibaba-cloud",
            "oracle-cloud",
            "ibm-cloud",
            "digitalocean",
            "cloudflare",
            "fastly",
        ],
        "skills": [
            "well-architected",
            "cost-optimization",
            "security-design",
            "high-availability",
            "disaster-recovery",
            "multi-region",
            "serverless",
            "containers",
            "hybrid-cloud",
            "data-architecture",
        ],
        "tools": ["aws-cdk", "pulumi", "terraform", "cloudformation", "arm-templates"],
        "certifications": ["aws-sap", "aws-saa", "azure-architect", "gcp-architect", "ccsp"],
    },
    "security-engineering": {
        "description": "Design and implement security controls and processes",
        "tech_stacks": ["siem", "soar", "edr", "xdr", "sase", "zero-trust", "identity", "pam", "dlp", "casb"],
        "skills": [
            "threat-modeling",
            "security-architecture",
            "iam",
            "pki",
            "encryption",
            "key-management",
            "network-security",
            "endpoint-security",
            "cloud-security",
            "data-security",
        ],
        "tools": ["splunk", "qradar", "sentinel", "crowdstrike", "paloalto", "okta"],
        "certifications": ["cissp", "cism", "cisa", "ccsp", "sans-giac"],
    },
    "appsec-engineering": {
        "description": "Embed security into software development lifecycle",
        "tech_stacks": ["sast", "dast", "iast", "sca", "container-scanning", "secret-scanning", "api-security", "waf"],
        "skills": [
            "secure-code-review",
            "threat-modeling",
            "pentest-web",
            "owasp-top10",
            "devsecops",
            "security-testing",
            "vulnerability-management",
            "sbom",
            "supply-chain-security",
        ],
        "tools": ["sonarqube", "snyk", "veracode", "checkmarx", "burpsuite", "semgrep"],
        "certifications": ["oscp", "gweb", "csslp", "ceh"],
    },
    "cloud-security": {
        "description": "Secure cloud infrastructure and workloads",
        "tech_stacks": ["aws-security", "azure-security", "gcp-security", "cspm", "cwpp", "cnapp", "ciem"],
        "skills": [
            "cloud-iam",
            "cloud-networking-security",
            "data-security-cloud",
            "compliance-cloud",
            "incident-response-cloud",
            "threat-detection",
        ],
        "tools": ["prisma-cloud", "wiz", "orca", "lacework", "aquasec", "twistlock"],
        "certifications": ["ccsp", "aws-security", "azure-security", "gcp-security"],
    },
    "penetration-testing": {
        "description": "Ethically test systems for security vulnerabilities",
        "tech_stacks": [
            "kali-linux",
            "parrot-os",
            "metasploit",
            "burpsuite",
            "nmap",
            "bloodhound",
            "cobalt-strike",
            "sliver",
        ],
        "skills": [
            "web-pentest",
            "network-pentest",
            "red-teaming",
            "social-engineering",
            "physical-security",
            "wireless-pentest",
            "cloud-pentest",
            "mobile-pentest",
            "api-pentest",
            "hardware-hacking",
        ],
        "tools": ["metasploit", "burpsuite", "nmap", "wireshark", "hashcat", "sqlmap"],
        "certifications": ["oscp", "osce", "osep", "crto", "ceh", "gpen"],
    },
    "data-engineering": {
        "description": "Build data pipelines and infrastructure for analytics",
        "tech_stacks": [
            "apache-spark",
            "apache-kafka",
            "apache-flink",
            "apache-airflow",
            "dbt",
            "dagster",
            "prefect",
            "databricks",
            "snowflake",
            "bigquery",
            "redshift",
            "duckdb",
            "delta-lake",
            "apache-iceberg",
        ],
        "skills": [
            "etl-elt",
            "stream-processing",
            "batch-processing",
            "data-modeling",
            "data-quality",
            "data-governance",
            "data-catalog",
            "lakehouse",
            "real-time-analytics",
            "cdc",
            "data-mesh",
        ],
        "tools": ["great-expectations", "monte-carlo", "dbt", "fivetran", "airbyte"],
        "certifications": ["aws-data", "gcp-data", "databricks-associate", "snowflake-pro"],
    },
    "data-science": {
        "description": "Extract insights and value from data using statistical methods",
        "tech_stacks": [
            "python-pandas",
            "r",
            "julia",
            "scala",
            "sql",
            "jupyter",
            "plotly",
            "tableau",
            "looker",
            "powerbi",
        ],
        "skills": [
            "statistical-analysis",
            "data-visualization",
            "hypothesis-testing",
            "regression",
            "classification",
            "clustering",
            "time-series",
            "a-b-testing",
            "causal-inference",
            "storytelling",
        ],
        "tools": ["pandas", "numpy", "scipy", "sklearn", "matplotlib", "seaborn", "altair"],
        "certifications": ["ibm-data-science", "google-data-analytics", "sas"],
    },
    "ml-engineering": {
        "description": "Build and deploy production machine learning systems",
        "tech_stacks": [
            "tensorflow",
            "pytorch",
            "jax",
            "keras",
            "huggingface",
            "mlflow",
            "kubeflow",
            "ray",
            "bentoml",
            "triton",
            "torchserve",
            "seldon",
            "kserve",
        ],
        "skills": [
            "model-training",
            "feature-engineering",
            "hyperparameter-tuning",
            "model-evaluation",
            "model-serving",
            "mlops",
            "monitoring-drift",
            "explainability",
            "fairness",
            "distributed-training",
        ],
        "tools": ["mlflow", "wandb", "dvc", "feast", "tecton", "evidently", "great-expectations"],
        "certifications": ["aws-mls", "gcp-mle", "databricks-ml", "nvidia-dli"],
    },
    "ai-llm-engineering": {
        "description": "Build applications and systems powered by large language models",
        "tech_stacks": [
            "openai",
            "anthropic",
            "google-gemini",
            "meta-llama",
            "mistral",
            "langchain",
            "llamaindex",
            "haystack",
            "semantic-kernel",
            "autogen",
            "crewai",
            "dspy",
        ],
        "skills": [
            "prompt-engineering",
            "rag",
            "fine-tuning",
            "agent-design",
            "llm-evaluation",
            "llm-security",
            "context-management",
            "embeddings",
            "vector-search",
            "llm-ops",
            "multi-modal",
        ],
        "tools": ["langsmith", "promptlayer", "trulens", "arize", "helicone", "vellum"],
        "certifications": ["deeplearning-ai", "google-genai", "aws-bedrock"],
    },
    "database-administration": {
        "description": "Manage, optimize and secure database systems",
        "tech_stacks": [
            "postgresql",
            "mysql",
            "oracle",
            "sqlserver",
            "db2",
            "mongodb",
            "cassandra",
            "dynamodb",
            "redis",
            "elasticsearch",
            "neo4j",
            "influxdb",
            "cockroachdb",
            "tidb",
            "vitess",
        ],
        "skills": [
            "query-optimization",
            "index-design",
            "replication",
            "sharding",
            "backup-recovery",
            "high-availability",
            "migration",
            "capacity-planning",
            "security-hardening",
            "performance-tuning",
        ],
        "tools": ["pgbadger", "explain-analyzer", "percona", "debezium", "flyway", "liquibase"],
        "certifications": ["oracle-dba", "mongodb-dba", "aws-database", "gcp-database"],
    },
    "systems-administration": {
        "description": "Manage and maintain computing infrastructure and operating systems",
        "tech_stacks": [
            "linux",
            "windows-server",
            "macos-server",
            "rhel",
            "ubuntu",
            "centos",
            "debian",
            "fedora",
            "windows-ad",
            "openldap",
            "ansible",
            "puppet",
            "chef",
        ],
        "skills": [
            "os-hardening",
            "patch-management",
            "user-management",
            "scripting",
            "backup-restore",
            "monitoring",
            "performance-tuning",
            "virtualization",
            "storage-management",
            "print-management",
        ],
        "tools": ["ansible", "puppet", "chef", "nagios", "zabbix", "graylog"],
        "certifications": ["rhcsa", "rhce", "mcsa", "lpic", "comptia-linux"],
    },
    "network-engineering": {
        "description": "Design, implement and manage network infrastructure",
        "tech_stacks": [
            "cisco-ios",
            "juniper-junos",
            "aruba",
            "fortinet",
            "paloalto",
            "checkpoint",
            "f5",
            "a10",
            "sd-wan",
            "sase",
            "nfv",
            "sdn",
        ],
        "skills": [
            "routing-switching",
            "firewall-management",
            "vpn",
            "load-balancing",
            "network-monitoring",
            "traffic-analysis",
            "wireless",
            "voip",
            "bgp-ospf-eigrp",
            "network-automation",
            "ipv6",
        ],
        "tools": ["wireshark", "gns3", "netbox", "napalm", "nornir", "batfish"],
        "certifications": ["ccna", "ccnp", "ccie", "jncia", "jncip", "pcnse"],
    },
    "embedded-systems": {
        "description": "Develop firmware and software for embedded and real-time systems",
        "tech_stacks": [
            "c",
            "cpp",
            "rust-embedded",
            "micropython",
            "freertos",
            "zephyr",
            "mbed",
            "arduino",
            "raspberry-pi",
            "stm32",
            "esp32",
            "avr",
            "arm-cortex",
        ],
        "skills": [
            "firmware-development",
            "rtos",
            "hardware-interfaces",
            "low-power-design",
            "debugging-jtag",
            "bootloaders",
            "device-drivers",
            "communication-protocols",
            "ota-updates",
        ],
        "tools": ["gdb", "openocd", "segger-jlink", "oscilloscope", "logic-analyzer"],
        "certifications": ["arm-embedded", "ieee-embedded"],
    },
    "iot-engineering": {
        "description": "Build connected device ecosystems and IoT platforms",
        "tech_stacks": [
            "mqtt",
            "coap",
            "lorawan",
            "zigbee",
            "zwave",
            "ble",
            "aws-iot",
            "azure-iot",
            "google-iot",
            "thingsboard",
            "nodered",
            "home-assistant",
        ],
        "skills": [
            "device-provisioning",
            "edge-computing",
            "fleet-management",
            "telemetry-collection",
            "ota-firmware",
            "security-iot",
            "data-ingestion",
            "digital-twin",
            "protocol-translation",
        ],
        "tools": ["mosquitto", "emqx", "influxdb", "grafana", "node-red", "flespi"],
        "certifications": ["aws-iot", "azure-iot", "ieee-iot"],
    },
    "blockchain-development": {
        "description": "Build decentralized applications and blockchain infrastructure",
        "tech_stacks": [
            "ethereum",
            "solana",
            "polygon",
            "avalanche",
            "cosmos",
            "hyperledger-fabric",
            "cardano",
            "near",
            "polkadot",
            "arbitrum",
        ],
        "skills": [
            "smart-contracts",
            "defi-protocols",
            "nft-platforms",
            "dao-governance",
            "cross-chain",
            "layer2",
            "wallet-integration",
            "cryptography",
            "consensus-mechanisms",
            "tokenomics",
        ],
        "tools": ["hardhat", "foundry", "truffle", "web3js", "ethersjs", "metamask"],
        "certifications": ["certified-blockchain", "solidity-developer", "hyperledger-admin"],
    },
    "game-development": {
        "description": "Create interactive games across platforms",
        "tech_stacks": [
            "unity",
            "unreal-engine",
            "godot",
            "cryengine",
            "pygame",
            "love2d",
            "phaser",
            "three-js",
            "playcanvas",
            "opengl",
            "vulkan",
            "directx",
            "metal",
        ],
        "skills": [
            "gameplay-programming",
            "physics-simulation",
            "ai-game",
            "graphics-programming",
            "shader-development",
            "networking-game",
            "audio-programming",
            "ui-hud",
            "optimization-game",
            "level-design",
        ],
        "tools": ["unity-editor", "unreal-editor", "blender", "maya", "substance", "perforce"],
        "certifications": ["unity-certified", "unreal-certified", "adobe-certified"],
    },
    "ar-vr-development": {
        "description": "Build augmented, virtual, and mixed reality experiences",
        "tech_stacks": [
            "unity-xr",
            "unreal-xr",
            "openxr",
            "webxr",
            "arkit",
            "arcore",
            "vuforia",
            "reality-kit",
            "oculus-sdk",
            "steamvr",
            "mixed-reality-toolkit",
        ],
        "skills": [
            "spatial-computing",
            "3d-interaction",
            "hand-tracking",
            "eye-tracking",
            "haptics",
            "spatial-audio",
            "world-mapping",
            "6dof-locomotion",
            "avatar-systems",
            "real-time-rendering",
        ],
        "tools": ["unity", "unreal", "blender", "maya", "substance-painter"],
        "certifications": ["unity-certified", "arvr-specialist"],
    },
    "qa-engineering": {
        "description": "Ensure software quality through testing strategies and automation",
        "tech_stacks": [
            "selenium",
            "playwright",
            "cypress",
            "webdriverio",
            "appium",
            "detox",
            "espresso",
            "xcuitest",
            "jest",
            "pytest",
            "junit",
            "testng",
            "nunit",
        ],
        "skills": [
            "test-strategy",
            "test-planning",
            "manual-testing",
            "automation-testing",
            "api-testing",
            "performance-testing",
            "security-testing",
            "accessibility-testing",
            "exploratory-testing",
            "regression-testing",
        ],
        "tools": ["jira", "testrail", "qtest", "zephyr", "allure", "reportportal"],
        "certifications": ["istqb-ctfl", "istqb-ctal", "aws-qa"],
    },
    "performance-engineering": {
        "description": "Ensure systems meet performance, scalability and reliability targets",
        "tech_stacks": ["jmeter", "k6", "locust", "gatling", "artillery", "wrk", "ab", "hey", "vegeta"],
        "skills": [
            "load-testing",
            "stress-testing",
            "scalability-testing",
            "profiling",
            "bottleneck-analysis",
            "capacity-planning",
            "benchmark-design",
            "chaos-engineering",
        ],
        "tools": ["grafana", "prometheus", "flamegraphs", "async-profiler", "perf"],
        "certifications": ["ptl", "cpe", "aws-sap"],
    },
    "technical-writing": {
        "description": "Create clear technical documentation and content",
        "tech_stacks": [
            "markdown",
            "asciidoc",
            "restructuredtext",
            "dita",
            "docusaurus",
            "mkdocs",
            "gitbook",
            "confluence",
            "swagger-openapi",
            "postman-docs",
        ],
        "skills": [
            "api-documentation",
            "user-guides",
            "tutorials",
            "reference-docs",
            "release-notes",
            "architecture-docs",
            "runbooks",
            "rfcs",
            "doc-as-code",
            "information-architecture",
            "style-guides",
        ],
        "tools": ["grammarly", "hemingway", "vale", "redocly", "readme-io"],
        "certifications": ["stc-cptc", "google-technical-writer"],
    },
    "developer-relations": {
        "description": "Bridge engineering teams with developer communities",
        "tech_stacks": [
            "documentation-platforms",
            "community-platforms",
            "sdk-tools",
            "content-management",
            "analytics",
            "developer-portals",
        ],
        "skills": [
            "community-building",
            "technical-blogging",
            "conference-speaking",
            "sdk-design",
            "developer-experience",
            "feedback-loops",
            "content-creation",
            "hackathon-organization",
            "advocacy",
        ],
        "tools": ["devrel-studio", "common-room", "orbit", "github", "discord", "slack"],
        "certifications": ["devrel-certified"],
    },
}

NON_TECH_ROLE_CATEGORIES = {
    "it-project-management": {
        "description": "Lead IT projects from initiation to delivery",
        "frameworks": ["pmp", "prince2", "agile-pm", "safe", "pmbok"],
        "skills": [
            "project-planning",
            "risk-management",
            "stakeholder-management",
            "budget-management",
            "resource-planning",
            "reporting",
            "vendor-management",
            "change-management",
            "scope-management",
        ],
        "tools": ["jira", "ms-project", "asana", "monday", "smartsheet", "trello"],
        "certifications": ["pmp", "capm", "prince2", "safe-agilist", "csm"],
    },
    "program-management": {
        "description": "Manage portfolios of related IT programs and initiatives",
        "frameworks": ["pgmp", "safe", "agile-portfolio", "okrs"],
        "skills": [
            "portfolio-management",
            "strategic-alignment",
            "governance",
            "dependency-management",
            "executive-reporting",
            "benefits-realization",
            "organizational-change",
            "roadmapping",
        ],
        "tools": ["planview", "clarity", "jira-align", "aha", "productboard"],
        "certifications": ["pgmp", "safe-spct", "togaf"],
    },
    "scrum-master": {
        "description": "Facilitate agile processes and remove impediments for teams",
        "frameworks": ["scrum", "kanban", "xp", "safe", "nexus", "less"],
        "skills": [
            "sprint-facilitation",
            "retrospectives",
            "impediment-removal",
            "coaching",
            "conflict-resolution",
            "metrics-tracking",
            "team-dynamics",
            "agile-transformation",
        ],
        "tools": ["jira", "confluence", "miro", "retrium", "parabol", "easy-agile"],
        "certifications": ["csm", "psm", "safe-sm", "ack"],
    },
    "product-management-tech": {
        "description": "Define product vision and roadmap for technology products",
        "frameworks": ["lean-product", "design-thinking", "jobs-to-be-done", "okrs"],
        "skills": [
            "product-discovery",
            "roadmapping",
            "user-research",
            "data-analysis",
            "competitive-analysis",
            "prioritization",
            "go-to-market",
            "a-b-testing",
            "kpi-definition",
            "stakeholder-alignment",
        ],
        "tools": ["productboard", "aha", "amplitude", "mixpanel", "figma", "dovetail"],
        "certifications": ["cspo", "pspo", "pma", "pragmatic-institute"],
    },
    "business-analysis": {
        "description": "Bridge business needs and technical solutions through analysis",
        "frameworks": ["babok", "agile-ba", "lean-ba"],
        "skills": [
            "requirements-elicitation",
            "process-modeling",
            "gap-analysis",
            "use-case-writing",
            "user-story-mapping",
            "bpml",
            "data-analysis",
            "stakeholder-facilitation",
            "feasibility",
        ],
        "tools": ["lucidchart", "visio", "miro", "confluence", "jira", "axure"],
        "certifications": ["cbap", "ccba", "ecba", "pmi-pba"],
    },
    "it-strategy": {
        "description": "Develop and execute technology strategy aligned with business goals",
        "frameworks": ["togaf", "cobit", "itil", "zachman", "feaf"],
        "skills": [
            "strategic-planning",
            "technology-roadmapping",
            "digital-transformation",
            "investment-planning",
            "vendor-strategy",
            "innovation-management",
            "executive-communication",
            "benchmarking",
        ],
        "tools": ["tableau", "powerbi", "gartner-tools", "ibo", "planview"],
        "certifications": ["togaf", "cio-certification", "itil-4-managing-professional"],
    },
    "enterprise-architecture": {
        "description": "Design and govern enterprise-wide technology architecture",
        "frameworks": ["togaf", "zachman", "feaf", "archimate", "sabsa"],
        "skills": [
            "business-architecture",
            "application-architecture",
            "data-architecture",
            "technology-architecture",
            "security-architecture",
            "architecture-governance",
            "pattern-design",
            "roadmapping",
        ],
        "tools": ["archimate", "sparx-ea", "bizzdesign", "leanix", "ardoq"],
        "certifications": ["togaf", "dodaf", "feac", "cisa"],
    },
    "it-governance": {
        "description": "Establish and maintain IT governance frameworks and controls",
        "frameworks": ["cobit", "itil", "iso27001", "nist", "gdpr", "sox"],
        "skills": [
            "policy-development",
            "control-design",
            "audit-support",
            "risk-management",
            "compliance-monitoring",
            "vendor-governance",
            "metrics-reporting",
            "board-reporting",
        ],
        "tools": ["servicenow-grc", "archer", "metricstream", "LogicGate"],
        "certifications": ["cgeit", "cisa", "crisc", "cism"],
    },
    "vendor-management": {
        "description": "Manage technology vendor relationships and performance",
        "frameworks": ["itil-supplier", "iso20000", "vmo"],
        "skills": [
            "contract-negotiation",
            "vendor-selection",
            "sla-management",
            "performance-monitoring",
            "relationship-management",
            "spend-optimization",
            "risk-assessment",
            "sourcing-strategy",
        ],
        "tools": ["coupa", "ariba", "servicenow", "apttus", "ivalua"],
        "certifications": ["ctpe", "cppm", "vm-certification"],
    },
    "it-procurement": {
        "description": "Manage technology purchasing, contracts and supplier relationships",
        "frameworks": ["cips", "napm", "agile-procurement"],
        "skills": [
            "rfp-rfq-management",
            "contract-management",
            "cost-benefit-analysis",
            "market-analysis",
            "negotiation",
            "supplier-diversity",
            "category-management",
            "spend-analysis",
        ],
        "tools": ["coupa", "ariba", "oracle-procurement", "jaggaer", "zip"],
        "certifications": ["cipp", "cpsm", "ccmp"],
    },
    "it-finance": {
        "description": "Manage IT financial planning, budgeting and cost optimization",
        "frameworks": ["tbm", "apptio", "zero-based-budgeting", "activity-based-costing"],
        "skills": [
            "it-budgeting",
            "cost-allocation",
            "financial-forecasting",
            "chargeback-showback",
            "roi-analysis",
            "cloud-cost-management",
            "capex-opex",
            "financial-reporting",
            "unit-economics",
        ],
        "tools": ["apptio", "cloudhealth", "cloudability", "finout", "vantage"],
        "certifications": ["cfm", "tbm-council", "finops-practitioner"],
    },
    "it-audit": {
        "description": "Assess IT controls, risks and compliance through independent review",
        "frameworks": ["cobit", "iso27001", "nist", "pci-dss", "sox", "hipaa"],
        "skills": [
            "audit-planning",
            "control-testing",
            "evidence-collection",
            "finding-documentation",
            "remediation-tracking",
            "report-writing",
            "data-analytics-audit",
            "continuous-auditing",
        ],
        "tools": ["acl-galvanize", "teammate", "teammate-analytics", "idea", "arbutus"],
        "certifications": ["cisa", "cia", "cissp", "cfe"],
    },
    "compliance-management": {
        "description": "Ensure adherence to regulatory requirements and standards",
        "frameworks": ["gdpr", "ccpa", "hipaa", "pci-dss", "sox", "iso27001", "nist-csf", "fedramp", "soc2"],
        "skills": [
            "regulatory-mapping",
            "gap-assessment",
            "policy-development",
            "training-programs",
            "audit-preparation",
            "incident-reporting",
            "data-privacy",
            "third-party-compliance",
        ],
        "tools": ["servicenow-grc", "vanta", "drata", "secureframe", "tugboat-logic"],
        "certifications": ["cipp", "cipm", "cipt", "crcm", "ccep"],
    },
    "change-management-it": {
        "description": "Manage organizational change driven by technology transformation",
        "frameworks": ["prosci-adkar", "kotter", "lewin", "mckinsey-7s"],
        "skills": [
            "change-impact-assessment",
            "stakeholder-engagement",
            "training-design",
            "communication-planning",
            "resistance-management",
            "adoption-measurement",
            "sponsorship-alignment",
            "sustainment",
        ],
        "tools": ["prosci-tools", "whatfix", "walkme", "pendo", "appcues"],
        "certifications": ["prosci-pct", "ccm", "acmp"],
    },
    "itsm-management": {
        "description": "Manage IT service delivery and support operations",
        "frameworks": ["itil4", "iso20000", "cobit", "verizon-itom"],
        "skills": [
            "incident-management",
            "problem-management",
            "change-management",
            "service-catalog",
            "capacity-management",
            "availability-management",
            "service-level-management",
            "continuous-improvement",
        ],
        "tools": ["servicenow", "jira-service-management", "freshservice", "ivanti", "cherwell"],
        "certifications": ["itil4-foundation", "itil4-mp", "itil4-sv", "hdi"],
    },
    "it-training": {
        "description": "Design and deliver IT learning programs and enablement",
        "frameworks": ["addie", "sam", "bloom-taxonomy", "kirkpatrick"],
        "skills": [
            "curriculum-design",
            "instructional-design",
            "e-learning",
            "virtual-training",
            "assessment-design",
            "learning-analytics",
            "lms-management",
            "mentoring",
            "coaching",
        ],
        "tools": ["articulate", "lectora", "adobe-captivate", "moodle", "cornerstone", "degreed"],
        "certifications": ["cptd", "atd", "ctts", "ccnp-training"],
    },
    "it-recruiting": {
        "description": "Source, assess and hire technology talent",
        "frameworks": ["competency-based", "structured-interviewing", "dei-hiring"],
        "skills": [
            "sourcing-strategy",
            "technical-screening",
            "interview-design",
            "candidate-experience",
            "employer-branding",
            "offer-management",
            "talent-pipeline",
            "hiring-analytics",
        ],
        "tools": ["greenhouse", "lever", "workday", "ashby", "linkedin-recruiter", "codility"],
        "certifications": ["shrm-cp", "phr", "airs-cdr", "tam"],
    },
    "it-operations-management": {
        "description": "Oversee day-to-day IT operations and service delivery",
        "frameworks": ["itil4", "cobit", "iso20000"],
        "skills": [
            "operations-planning",
            "team-leadership",
            "budget-management",
            "vendor-oversight",
            "escalation-management",
            "kpi-reporting",
            "continuous-improvement",
            "capacity-planning",
        ],
        "tools": ["servicenow", "pagerduty", "datadog", "new-relic", "opsgenie"],
        "certifications": ["itil4-mp", "pmp", "cobit-2019"],
    },
    "it-support-helpdesk": {
        "description": "Provide technical assistance to end users and internal staff",
        "frameworks": ["itil4", "hdi", "kccs"],
        "skills": [
            "troubleshooting",
            "active-directory",
            "o365-support",
            "hardware-support",
            "software-installation",
            "remote-support",
            "documentation",
            "escalation",
            "customer-service",
        ],
        "tools": ["servicenow", "jira-sm", "zendesk", "teamviewer", "bomgar", "intune"],
        "certifications": ["comptia-a+", "itil4-foundation", "hda", "mcp"],
    },
    "it-marketing": {
        "description": "Market technology products, services and the IT brand",
        "frameworks": ["product-marketing", "demand-generation", "account-based-marketing"],
        "skills": [
            "product-positioning",
            "content-marketing",
            "digital-marketing",
            "event-marketing",
            "analyst-relations",
            "campaign-management",
            "seo-sem",
            "marketing-analytics",
        ],
        "tools": ["marketo", "hubspot", "salesforce", "google-analytics", "semrush", "drift"],
        "certifications": ["pma", "hubspot-certified", "google-ads", "cmp"],
    },
    "customer-success-tech": {
        "description": "Ensure technology customers achieve their desired outcomes",
        "frameworks": ["cs-playbooks", "health-scoring", "qbr", "expansion"],
        "skills": [
            "onboarding",
            "adoption-strategy",
            "churn-prevention",
            "upselling",
            "technical-escalation",
            "success-planning",
            "advocacy",
            "renewal-management",
            "executive-business-reviews",
        ],
        "tools": ["gainsight", "totango", "churnzero", "catalyst", "salesforce"],
        "certifications": ["csm-certified", "ccsm", "pcsm"],
    },
    "it-risk-management": {
        "description": "Identify, assess and mitigate technology risks",
        "frameworks": ["nist-rmf", "iso31000", "cobit-risk", "fair"],
        "skills": [
            "risk-identification",
            "risk-quantification",
            "risk-treatment",
            "risk-monitoring",
            "third-party-risk",
            "operational-risk",
            "cyber-risk",
            "business-continuity",
        ],
        "tools": ["servicenow-irm", "archer", "metricstream", "risklens", "safe"],
        "certifications": ["crisc", "cissp", "cism", "iso31000-practitioner"],
    },
    "digital-transformation": {
        "description": "Lead organizational digital transformation initiatives",
        "frameworks": ["mckinsey-dt", "mit-dt", "lean-digital", "agile-transformation"],
        "skills": [
            "transformation-strategy",
            "innovation-management",
            "cultural-change",
            "capability-building",
            "ecosystem-design",
            "data-strategy",
            "customer-journey",
            "operating-model-design",
        ],
        "tools": ["miro", "mural", "aha", "planview", "servicenow"],
        "certifications": ["dta-certified", "togaf", "prosci-pct"],
    },
    "data-governance": {
        "description": "Establish and enforce data policies, standards and stewardship",
        "frameworks": ["dama-dmbok", "cmmi-data", "edm-council"],
        "skills": [
            "data-policy",
            "metadata-management",
            "data-quality-program",
            "data-stewardship",
            "master-data",
            "data-lineage",
            "privacy-governance",
            "data-literacy",
        ],
        "tools": ["collibra", "alation", "atlan", "informatica-axon", "microsoft-purview"],
        "certifications": ["cdmp", "dcam", "cipp"],
    },
    "it-communications": {
        "description": "Manage internal and external IT communications and stakeholder relations",
        "frameworks": ["integrated-communications", "change-comms", "crisis-comms"],
        "skills": [
            "executive-communications",
            "technical-writing",
            "newsletter",
            "intranet-management",
            "town-halls",
            "crisis-communications",
            "social-media",
            "pr-media-relations",
        ],
        "tools": ["poppulo", "staffbase", "mailchimp", "wordpress", "sharepoint"],
        "certifications": ["iabc", "prsa", "google-analytics"],
    },
}

EXPERIENCE_VARIANTS = [
    "generalist",
    "specialist",
    "consultant",
    "contractor",
    "advisor",
    "manager",
    "director",
    "vp",
    "cto",
    "cio",
    "ciso",
    "cdo",
    "team-lead",
    "tech-lead",
    "engineering-manager",
    "head-of",
    "remote",
    "hybrid",
    "on-site",
]

DOMAIN_SPECIALIZATIONS = [
    "startup",
    "enterprise",
    "government",
    "nonprofit",
    "regulated-industry",
    "global",
    "regional",
    "b2b",
    "b2c",
    "marketplace",
    "platform",
]

# ─────────────────────────────────────────────
# GENERATOR
# ─────────────────────────────────────────────


def sanitize(name: str) -> str:
    return name.replace(" ", "-").replace("/", "-").lower()


def generate_agent(
    role_id: str, category: str, category_data: dict, variant: dict, agent_index: int, is_technical: bool
) -> dict:
    seniority = variant.get("seniority", "mid")
    industry = variant.get("industry", "")
    cloud = variant.get("cloud", "")
    extra = variant.get("extra", "")

    stacks_key = "tech_stacks" if "tech_stacks" in category_data else "frameworks"
    primary_stack = category_data[stacks_key][agent_index % len(category_data[stacks_key])]

    skills = category_data.get("skills", [])
    tools = category_data.get("tools", [])
    certs = category_data.get("certifications", [])

    tags = [seniority, category, "it-role"]
    if industry:
        tags.append(industry)
    if cloud:
        tags.append(cloud)
    if extra:
        tags.append(extra)
    if is_technical:
        tags.append("technical")
    else:
        tags.append("non-technical")

    name_parts = [seniority.title(), category.replace("-", " ").title()]
    if extra:
        name_parts.append(f"({extra.replace('-', ' ').title()})")
    if industry:
        name_parts.append(f"[{industry.upper()}]")

    agent = {
        "id": f"agent-{agent_index:05d}",
        "name": " ".join(name_parts),
        "role": category,
        "type": "technical" if is_technical else "non-technical",
        "seniority": seniority,
        "description": category_data["description"],
        "primary_stack": primary_stack,
        "industry_focus": industry or "cross-industry",
        "cloud_preference": cloud or "cloud-agnostic",
        "skills": skills[:8],
        "tools": tools[:5],
        "certifications": certs[:3],
        "tags": list(set(tags)),
        "guardrails_profile": "standard",
        "human_input_required": seniority in ["architect", "principal", "distinguished", "fellow"],
        "package_policy": "semver-minor-auto-upgrade",
        "folder_structure_template": f"templates/project-structures/{primary_stack.split('-')[0]}-service"
        if is_technical
        else "templates/project-structures/generic-project",
        "created_by": "it-agents-generator-v1",
        "version": "1.0.0",
    }
    return agent


def generate_all_agents() -> list:
    agents = []
    idx = 1

    all_categories = []
    for cat_id, cat_data in TECH_ROLE_CATEGORIES.items():
        all_categories.append((cat_id, cat_data, True))
    for cat_id, cat_data in NON_TECH_ROLE_CATEGORIES.items():
        all_categories.append((cat_id, cat_data, False))

    # Build variants to hit 10,000
    target = 10000
    variants_pool = []

    for seniority in SENIORITY_LEVELS:
        for industry in [""] + INDUSTRIES[:5]:
            for cloud in [""] + CLOUD_PROVIDERS[:3]:
                for extra in [""] + EXPERIENCE_VARIANTS[:4]:
                    variants_pool.append({"seniority": seniority, "industry": industry, "cloud": cloud, "extra": extra})

    variant_iter = itertools.cycle(variants_pool)

    per_category = target // len(all_categories)
    remainder = target % len(all_categories)

    for cat_idx, (cat_id, cat_data, is_tech) in enumerate(all_categories):
        count = per_category + (1 if cat_idx < remainder else 0)
        for i in range(count):
            variant = next(variant_iter)
            agent = generate_agent(cat_id, cat_id, cat_data, variant, idx, is_tech)
            agents.append(agent)
            idx += 1

    return agents


def save_agents(agents: list, output_dir: str):
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Group by type then role
    by_role = {}
    for agent in agents:
        role = agent["role"]
        agent_type = agent["type"]
        key = f"{agent_type}/{role}"
        by_role.setdefault(key, []).append(agent)

    for key, role_agents in by_role.items():
        role_dir = Path(output_dir) / key
        role_dir.mkdir(parents=True, exist_ok=True)

        # Save individual files (max 50 per role folder for readability)
        for i, agent in enumerate(role_agents):
            agent_file = role_dir / f"{agent['id']}.yaml"
            with open(agent_file, "w") as f:
                yaml.dump(agent, f, default_flow_style=False, sort_keys=False)

    # Save master index
    index = [
        {"id": a["id"], "name": a["name"], "role": a["role"], "type": a["type"], "seniority": a["seniority"]}
        for a in agents
    ]
    with open(Path(output_dir) / "agents_index.json", "w") as f:
        json.dump(index, f, indent=2)

    print(f"Generated {len(agents)} agents in {output_dir}")
    print(f"Roles covered: {len(set(a['role'] for a in agents))}")


if __name__ == "__main__":
    print("Generating 10,000 IT agents...")
    agents = generate_all_agents()
    save_agents(agents, "agents")
    print("Done!")
