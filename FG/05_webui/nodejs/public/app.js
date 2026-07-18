'use strict';

const STORAGE_KEY = 'cg_rti_assistant_conversations_v1';
const ACTIVE_KEY = 'cg_rti_assistant_active_conversation_v1';
const PIO_MODE_KEY = 'cg_rti_assistant_pio_mode_v1';
const LANGUAGE_MODE_KEY = 'cg_rti_assistant_language_mode_v1';
const MAX_CONVERSATION_CONTEXT_MESSAGES = 5;
const MAX_CONVERSATION_CONTEXT_MESSAGE_CHARS = 1200;
const MAX_HISTORY_ITEMS = 24;
const AUTH_TOKEN_KEY = 'cg_rti_auth_token';
const AUTH_USER_KEY = 'cg_rti_auth_user';

function authToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY) || sessionStorage.getItem(AUTH_TOKEN_KEY) || '';
}

function authUser() {
  const value = localStorage.getItem(AUTH_USER_KEY) || sessionStorage.getItem(AUTH_USER_KEY);
  try { return value ? JSON.parse(value) : null; } catch (_) { return null; }
}

function clearAuth() {
  [localStorage, sessionStorage].forEach(storage => {
    storage.removeItem(AUTH_TOKEN_KEY);
    storage.removeItem(AUTH_USER_KEY);
  });
}

function saveAuth(token, user, remember) {
  clearAuth();
  const storage = remember ? localStorage : sessionStorage;
  storage.setItem(AUTH_TOKEN_KEY, token);
  storage.setItem(AUTH_USER_KEY, JSON.stringify(user));
}

const DEFAULT_PROMPT_KEYS = [
  'promptRegister',
  'promptFileRti',
  'promptPayFees',
  'promptFirstAppeal',
  'promptCheckStatus',
  'promptFindPio'
];

const TRANSLATIONS = {
  en: {
    documentTitle: 'RTI Assistant - CG Portal',
    chatHistory: 'Chat history',
    cgGovernmentLogo: 'Chhattisgarh government logo',
    brandTitle: 'RTI Assistant',
    brandSubtitle: 'CG RTI Portal',
    newChat: 'New chat',
    botStatus: 'Bot status',
    checkingBotStatus: 'Checking bot status',
    assistant: 'Assistant',
    knowledgeBase: 'Knowledge base',
    documents: 'Documents',
    refreshBot: 'Refresh bot',
    history: 'History',
    citizenHelpdesk: 'Chhattisgarh citizen helpdesk',
    languageToggleLabel: 'Site and answer language',
    englishLanguage: 'English',
    hindiLanguage: 'Hindi',
    pioMode: 'PIO Mode',
    on: 'On', off: 'Off',
    pioAdvisoryEnabled: 'PIO advisory enabled',
    publicGuidance: 'Public guidance',
    clear: 'Clear',
    welcomeTitle: 'How can I help with RTI?',
    welcomeDescription: 'Ask about the CG RTI portal, filing steps, fees, appeals, application status, PIO contacts, RTI Act basics, or portal documents.',
    promptRegister: 'How do I register on the CG RTI portal?',
    promptFileRti: 'How do I file an RTI application?',
    promptPayFees: 'How do I pay RTI fees?',
    promptFirstAppeal: 'How do I file a first appeal?',
    promptCheckStatus: 'How can I check application status?',
    promptFindPio: 'How do I find PIO contact details?',
    uploadPdf: 'Upload PDF', send: 'Send',
    checkingAssistantStatus: 'Checking assistant status',
    sourceChunks: 'Source chunks', sources: 'Sources', close: 'Close',
    documentPreview: 'Document preview', document: 'Document', closePdf: 'Close PDF',
    loadingDocument: 'Loading document', pdfViewer: 'PDF viewer',
    defaultQueryPlaceholder: 'Ask about RTI portal steps, fees, appeals, status, PIO details, or RTI Act sections...',
    pioQueryPlaceholder: 'Ask any RTI question, or paste an RTI application and request a PIO advisory response...',
    noHistory: 'No history yet.', you: 'YOU',
    answeredIn: 'Answered in {time}', viewSources: 'View sources',
    analysisDetails: 'Analysis details', rtiExtraction: 'RTI extraction',
    legalAnalysis: 'Legal analysis', appliedProvisions: 'Applied RTI Act provisions',
    validationResult: 'Validation result',
    decisionReferences: 'CIC/CGSIC decision references ({count})',
    noDecisionReferences: 'No decision references were attached.',
    noSourcePdfName: 'No source PDF file name was attached.', openFile: 'Open {filename}',
    generatingPrecedentAdvisory: 'Generating precedent-informed advisory...',
    precedentAdvisoryGenerated: 'Precedent-informed advisory generated',
    generatePrecedentAdvisory: 'Generate precedent-informed PIO advisory',
    referencesNotAdded: 'CIC/CGSIC references were not added.',
    searchingDecisions: 'Searching CIC/CGSIC decisions...',
    addSupportingReferences: 'Add supporting CIC/CGSIC decision references?',
    yesAddReferences: 'Yes, add references',
    yesAddReferencesMessage: 'Yes, add CIC/CGSIC references', no: 'No',
    advisoryNotLinkable: 'This advisory cannot be linked to a precedent search.',
    referenceSearchFailed: 'CIC/CGSIC reference search failed.',
    networkRetrievingReferences: 'Network error while retrieving CIC/CGSIC references.',
    generateReferencesFirst: 'Generate CIC/CGSIC references first.',
    advisoryGenerationFailed: 'Precedent-informed advisory generation failed.',
    networkGeneratingAdvisory: 'Network error while generating precedent-informed advisory.',
    unableGenerateAdvisory: 'Unable to generate precedent-informed advisory: {error}',
    networkError: 'Network error.', ready: 'Ready', loading: 'Loading...',
    botNeedsAttention: 'Bot needs attention', ocrUnavailable: 'OCR unavailable ({model})',
    allSystemsOperational: 'All systems operational', botStatusPending: 'Bot status pending',
    refreshing: 'Refreshing...', refreshingBot: 'Refreshing bot...',
    botRefreshed: 'Bot refreshed successfully', refreshFailed: 'Refresh failed',
    refreshBeforeAsking: 'Refresh bot before asking', backendUnavailable: 'Backend unavailable',
    cannotReachBackend: 'Cannot reach backend', dbStatusFailed: 'Database status check failed',
    checking: 'checking', failed: 'failed',
    offline: 'offline', available: 'available', unavailable: 'unavailable', statusReady: 'ready',
    assistantUnavailable: 'Assistant unavailable', points: '{count} pts', retrieving: 'Retrieving...',
    analysingRti: 'Analysing RTI application and legal provisions...',
    retrievingContext: 'Retrieving relevant context...', generatingAnswer: 'Generating answer...',
    queryFailed: 'Query failed', unableToAnswer: 'Unable to answer: {error}',
    backendNetworkError: 'Network error - is the backend running?',
    pleaseUploadPdf: 'Please upload a PDF file.', uploadedPdf: 'Uploaded PDF: {filename}',
    uploadingPdf: 'Uploading PDF...', extractingPdf: 'Extracting PDF text...',
    pdfProcessed: 'PDF processed and PIO advisory generated.',
    uploadFailed: 'Upload failed (HTTP {status})',
    unableProcessPdf: 'Unable to process uploaded PDF: {error}',
    networkUploadingPdf: 'Network error while uploading PDF.',
    informationRequested: 'Information Requested', commissionObservation: 'Commission Observation',
    commissionFinding: 'Commission Finding', finalOrder: 'Final Order', pioLearning: 'PIO Learning',
    precedentSummary: 'Precedent Summary', groundsForAppeal: 'Grounds for Appeal',
    hearingSubmissions: 'Hearing Submissions', caseMetadata: 'Case Metadata',
    relevantPassage: 'Relevant Passage', officerDirectory: 'CG RTI Officer Directory',
    officerRegistry: 'CG RTI Officer Registry', role: 'Role', officer: 'Officer',
    designation: 'Designation', department: 'Department', district: 'District', office: 'Office',
    officeCode: 'Office code', email: 'Email', address: 'Address',
    officerDirectoryRecord: 'Officer directory record', unknown: 'unknown',
    case: 'Case: {value}', authority: 'Authority: {value}', hearing: 'Hearing: {value}',
    outcome: 'Outcome: {value}', expandPassage: 'Expand passage', passage: 'Passage',
    viewPdf: 'View PDF', viewStructure: 'View structure',
    structureUnavailable: 'structured.md is not available for this document',
    openMarkdown: 'Open extracted Markdown', loadingPdf: 'Loading PDF',
    pdfFetchFailed: 'PDF fetch failed: {status}', couldNotLoadPdf: 'Could not load PDF: {error}',
    loadingStructure: 'Loading structure', structureRequestFailed: 'structured.md request failed',
    couldNotLoadStructure: 'Could not load structure: {error}',
    publicDomainVerification: 'Public-domain verification', verificationStatus: 'Status',
    verificationFound: 'Found', verificationPartiallyFound: 'Partially found',
    verificationNotFound: 'Not found', verificationSourceUnavailable: 'Source unavailable',
    verifiedOfficialDocuments: 'Verified official documents: {count}',
    searchedOfficialDomains: 'Searched official domains', lastChecked: 'Last checked',
    availableFields: 'Available', missingFields: 'Missing', noneReported: 'None reported',
    officialSource: 'Official source', publicationDate: 'Publication date',
    pageNumber: 'Page', sectionHeading: 'Section', matchedEvidence: 'Matched evidence',
    openOfficialSource: 'Open official source: {domain}',
    someOfficialSourcesUnavailable: 'Some official sources could not be checked.',
    retryUnavailableSources: 'Retry unavailable sources',
    retryingVerification: 'Retrying verification...',
    verificationRetryFailed: 'Public-domain verification retry failed.',
    searchOfficialWeb: 'Search official websites',
    searchingOfficialWeb: 'Searching official websites...',
    officialWebSearchFailed: 'Official website search failed.'
  },
  hi: {
    documentTitle: 'आरटीआई सहायक - छत्तीसगढ़ पोर्टल', chatHistory: 'चैट इतिहास',
    cgGovernmentLogo: 'छत्तीसगढ़ शासन का प्रतीक', brandTitle: 'आरटीआई सहायक',
    brandSubtitle: 'छत्तीसगढ़ आरटीआई पोर्टल', newChat: 'नई चैट',
    botStatus: 'बॉट की स्थिति', checkingBotStatus: 'बॉट की स्थिति जाँची जा रही है',
    assistant: 'सहायक', knowledgeBase: 'ज्ञान आधार', documents: 'दस्तावेज़',
    refreshBot: 'बॉट रीफ़्रेश करें', history: 'इतिहास',
    citizenHelpdesk: 'छत्तीसगढ़ नागरिक सहायता केंद्र',
    languageToggleLabel: 'वेबसाइट और उत्तर की भाषा',
    englishLanguage: 'अंग्रेज़ी', hindiLanguage: 'हिंदी', pioMode: 'PIO मोड',
    on: 'चालू', off: 'बंद', pioAdvisoryEnabled: 'PIO सलाह सक्षम',
    publicGuidance: 'सार्वजनिक मार्गदर्शन', clear: 'साफ़ करें',
    welcomeTitle: 'आरटीआई में मैं आपकी कैसे सहायता कर सकता हूँ?',
    welcomeDescription: 'छत्तीसगढ़ आरटीआई पोर्टल, आवेदन प्रक्रिया, शुल्क, अपील, आवेदन की स्थिति, PIO संपर्क, आरटीआई अधिनियम या पोर्टल दस्तावेज़ों के बारे में पूछें।',
    promptRegister: 'छत्तीसगढ़ आरटीआई पोर्टल पर पंजीकरण कैसे करें?',
    promptFileRti: 'आरटीआई आवेदन कैसे दाखिल करें?', promptPayFees: 'आरटीआई शुल्क का भुगतान कैसे करें?',
    promptFirstAppeal: 'प्रथम अपील कैसे दाखिल करें?', promptCheckStatus: 'आवेदन की स्थिति कैसे जाँचें?',
    promptFindPio: 'PIO के संपर्क विवरण कैसे खोजें?', uploadPdf: 'PDF अपलोड करें', send: 'भेजें',
    checkingAssistantStatus: 'सहायक की स्थिति जाँची जा रही है', sourceChunks: 'स्रोत अंश',
    sources: 'स्रोत', close: 'बंद करें', documentPreview: 'दस्तावेज़ पूर्वावलोकन',
    document: 'दस्तावेज़', closePdf: 'PDF बंद करें', loadingDocument: 'दस्तावेज़ लोड हो रहा है',
    pdfViewer: 'PDF दर्शक',
    defaultQueryPlaceholder: 'आरटीआई पोर्टल प्रक्रिया, शुल्क, अपील, स्थिति, PIO विवरण या आरटीआई अधिनियम की धाराओं के बारे में पूछें...',
    pioQueryPlaceholder: 'आरटीआई से जुड़ा कोई भी प्रश्न पूछें, या आरटीआई आवेदन चिपकाकर PIO सलाह माँगें...',
    noHistory: 'अभी कोई इतिहास नहीं है।', you: 'आप', answeredIn: '{time} में उत्तर दिया गया',
    viewSources: 'स्रोत देखें', analysisDetails: 'विश्लेषण विवरण', rtiExtraction: 'आरटीआई निष्कर्षण',
    legalAnalysis: 'कानूनी विश्लेषण', appliedProvisions: 'लागू आरटीआई अधिनियम प्रावधान',
    validationResult: 'सत्यापन परिणाम', decisionReferences: 'CIC/CGSIC निर्णय संदर्भ ({count})',
    noDecisionReferences: 'कोई निर्णय संदर्भ संलग्न नहीं किया गया।',
    noSourcePdfName: 'स्रोत PDF फ़ाइल का नाम संलग्न नहीं किया गया।', openFile: '{filename} खोलें',
    generatingPrecedentAdvisory: 'नज़ीर-आधारित सलाह तैयार की जा रही है...',
    precedentAdvisoryGenerated: 'नज़ीर-आधारित सलाह तैयार हो गई',
    generatePrecedentAdvisory: 'नज़ीर-आधारित PIO सलाह तैयार करें',
    referencesNotAdded: 'CIC/CGSIC संदर्भ नहीं जोड़े गए।',
    searchingDecisions: 'CIC/CGSIC निर्णय खोजे जा रहे हैं...',
    addSupportingReferences: 'समर्थन में CIC/CGSIC निर्णय संदर्भ जोड़ें?',
    yesAddReferences: 'हाँ, संदर्भ जोड़ें', yesAddReferencesMessage: 'हाँ, CIC/CGSIC संदर्भ जोड़ें', no: 'नहीं',
    advisoryNotLinkable: 'इस सलाह को नज़ीर खोज से नहीं जोड़ा जा सकता।',
    referenceSearchFailed: 'CIC/CGSIC संदर्भ खोज विफल रही।',
    networkRetrievingReferences: 'CIC/CGSIC संदर्भ प्राप्त करते समय नेटवर्क त्रुटि हुई।',
    generateReferencesFirst: 'पहले CIC/CGSIC संदर्भ तैयार करें।',
    advisoryGenerationFailed: 'नज़ीर-आधारित सलाह तैयार नहीं हो सकी।',
    networkGeneratingAdvisory: 'नज़ीर-आधारित सलाह तैयार करते समय नेटवर्क त्रुटि हुई।',
    unableGenerateAdvisory: 'नज़ीर-आधारित सलाह तैयार नहीं की जा सकी: {error}',
    networkError: 'नेटवर्क त्रुटि।', ready: 'तैयार', loading: 'लोड हो रहा है...',
    botNeedsAttention: 'बॉट पर ध्यान देना आवश्यक है', ocrUnavailable: 'OCR उपलब्ध नहीं है ({model})',
    allSystemsOperational: 'सभी प्रणालियाँ कार्यरत हैं', botStatusPending: 'बॉट की स्थिति लंबित है',
    refreshing: 'रीफ़्रेश हो रहा है...', refreshingBot: 'बॉट रीफ़्रेश हो रहा है...',
    botRefreshed: 'बॉट सफलतापूर्वक रीफ़्रेश हुआ', refreshFailed: 'रीफ़्रेश विफल रहा',
    refreshBeforeAsking: 'प्रश्न पूछने से पहले बॉट रीफ़्रेश करें', backendUnavailable: 'बैकएंड उपलब्ध नहीं है',
    cannotReachBackend: 'बैकएंड से संपर्क नहीं हो सका', dbStatusFailed: 'डेटाबेस स्थिति की जाँच विफल रही',
    checking: 'जाँच जारी', failed: 'विफल',
    offline: 'ऑफ़लाइन', available: 'उपलब्ध', unavailable: 'अनुपलब्ध', statusReady: 'तैयार',
    assistantUnavailable: 'सहायक उपलब्ध नहीं है', points: '{count} बिंदु',
    retrieving: 'जानकारी प्राप्त की जा रही है...', queryFailed: 'प्रश्न संसाधित नहीं हो सका',
    analysingRti: 'RTI आवेदन और कानूनी प्रावधानों का विश्लेषण किया जा रहा है...',
    retrievingContext: 'संबंधित संदर्भ प्राप्त किया जा रहा है...', generatingAnswer: 'उत्तर तैयार किया जा रहा है...',
    unableToAnswer: 'उत्तर नहीं दिया जा सका: {error}',
    backendNetworkError: 'नेटवर्क त्रुटि - क्या बैकएंड चल रहा है?',
    pleaseUploadPdf: 'कृपया PDF फ़ाइल अपलोड करें।', uploadedPdf: 'अपलोड की गई PDF: {filename}',
    uploadingPdf: 'PDF अपलोड हो रही है...', extractingPdf: 'PDF से पाठ निकाला जा रहा है...',
    pdfProcessed: 'PDF संसाधित हुई और PIO सलाह तैयार हो गई।',
    uploadFailed: 'अपलोड विफल रहा (HTTP {status})',
    unableProcessPdf: 'अपलोड की गई PDF संसाधित नहीं हो सकी: {error}',
    networkUploadingPdf: 'PDF अपलोड करते समय नेटवर्क त्रुटि हुई।',
    informationRequested: 'माँगी गई जानकारी', commissionObservation: 'आयोग की टिप्पणी',
    commissionFinding: 'आयोग का निष्कर्ष', finalOrder: 'अंतिम आदेश', pioLearning: 'PIO सीख',
    precedentSummary: 'नज़ीर सारांश', groundsForAppeal: 'अपील के आधार',
    hearingSubmissions: 'सुनवाई में प्रस्तुतियाँ', caseMetadata: 'प्रकरण मेटाडेटा',
    relevantPassage: 'प्रासंगिक अंश', officerDirectory: 'छत्तीसगढ़ आरटीआई अधिकारी निर्देशिका',
    officerRegistry: 'छत्तीसगढ़ आरटीआई अधिकारी रजिस्ट्री', role: 'भूमिका', officer: 'अधिकारी',
    designation: 'पदनाम', department: 'विभाग', district: 'जिला', office: 'कार्यालय',
    officeCode: 'कार्यालय कोड', email: 'ईमेल', address: 'पता',
    officerDirectoryRecord: 'अधिकारी निर्देशिका रिकॉर्ड', unknown: 'अज्ञात',
    case: 'प्रकरण: {value}', authority: 'प्राधिकरण: {value}', hearing: 'सुनवाई: {value}',
    outcome: 'परिणाम: {value}', expandPassage: 'अंश विस्तार से देखें', passage: 'अंश',
    viewPdf: 'PDF देखें', viewStructure: 'संरचना देखें',
    structureUnavailable: 'इस दस्तावेज़ के लिए structured.md उपलब्ध नहीं है',
    openMarkdown: 'निकाला गया Markdown खोलें', loadingPdf: 'PDF लोड हो रही है',
    pdfFetchFailed: 'PDF प्राप्त नहीं हो सकी: {status}', couldNotLoadPdf: 'PDF लोड नहीं हो सकी: {error}',
    loadingStructure: 'संरचना लोड हो रही है', structureRequestFailed: 'structured.md अनुरोध विफल रहा',
    couldNotLoadStructure: 'संरचना लोड नहीं हो सकी: {error}',
    publicDomainVerification: 'सार्वजनिक-डोमेन सत्यापन', verificationStatus: 'स्थिति',
    verificationFound: 'मिला', verificationPartiallyFound: 'आंशिक रूप से मिला',
    verificationNotFound: 'नहीं मिला', verificationSourceUnavailable: 'स्रोत अनुपलब्ध',
    verifiedOfficialDocuments: 'सत्यापित आधिकारिक दस्तावेज़: {count}',
    searchedOfficialDomains: 'खोजे गए आधिकारिक डोमेन', lastChecked: 'अंतिम जाँच',
    availableFields: 'उपलब्ध', missingFields: 'अनुपलब्ध', noneReported: 'कोई विवरण नहीं',
    officialSource: 'आधिकारिक स्रोत', publicationDate: 'प्रकाशन तिथि',
    pageNumber: 'पृष्ठ', sectionHeading: 'अनुभाग', matchedEvidence: 'मिलान किया गया साक्ष्य',
    openOfficialSource: 'आधिकारिक स्रोत खोलें: {domain}',
    someOfficialSourcesUnavailable: 'कुछ आधिकारिक स्रोतों की जाँच नहीं हो सकी।',
    retryUnavailableSources: 'अनुपलब्ध स्रोतों को पुनः जाँचें',
    retryingVerification: 'सत्यापन की पुनः जाँच जारी है...',
    verificationRetryFailed: 'सार्वजनिक-डोमेन सत्यापन की पुनः जाँच विफल रही।',
    searchOfficialWeb: 'आधिकारिक वेबसाइट खोजें',
    searchingOfficialWeb: 'आधिकारिक वेबसाइटों पर खोज जारी है...',
    officialWebSearchFailed: 'आधिकारिक वेबसाइट खोज विफल रही।'
  }
};

const CG_GOV_LOGO = '/assets/cg_gov_logo.png';
const PRECEDENT_YES_CONFIRMATIONS = new Set([
  'yes', 'y', 'ok', 'okay', 'haan', 'ha', 'हाँ', 'हां'
]);
const PRECEDENT_NO_CONFIRMATIONS = new Set([
  'no', 'n', 'nahin', 'nahi', 'नहीं', 'नहि', 'ना'
]);
const WEB_VERIFICATION_VISIBLE_STATUSES = new Set([
  'FOUND',
  'PARTIALLY_FOUND',
  'NOT_FOUND',
  'SOURCE_UNAVAILABLE'
]);
const WEB_VERIFICATION_STATUS_KEYS = {
  FOUND: 'verificationFound',
  PARTIALLY_FOUND: 'verificationPartiallyFound',
  NOT_FOUND: 'verificationNotFound',
  SOURCE_UNAVAILABLE: 'verificationSourceUnavailable'
};


const $ = id => document.getElementById(id);

const ui = {
  authScreen: $('auth-screen'),
  appShell: $('app-shell'),
  authRoleSelector: $('auth-role-selector'),
  authRoleOptions: Array.from(document.querySelectorAll('[data-login-role]')),
  loginForm: $('login-form'),
  loginIdentifier: $('login-identifier'),
  loginPassword: $('login-password'),
  rememberLogin: $('remember-login'),
  loginError: $('login-error'),
  loginSubmit: $('login-submit'),
  signupForm: $('signup-form'),
  signupName: $('signup-name'),
  signupUsername: $('signup-username'),
  signupEmail: $('signup-email'),
  signupPassword: $('signup-password'),
  signupConfirm: $('signup-confirm'),
  signupMessage: $('signup-message'),
  signupSubmit: $('signup-submit'),
  showSignup: $('show-signup'),
  showLogin: $('show-login'),
  forgotPassword: $('forgot-password'),
  signedInAvatar: $('signed-in-avatar'),
  signedInName: $('signed-in-name'),
  logoutButton: $('logout-button'),
  newChat: $('new-chat'),
  clearChat: $('clear-chat'),
  historyList: $('history-list'),
  btnInit: $('btn-init'),
  btnSend: $('btn-send'),
  languageOptions: Array.from(document.querySelectorAll('[data-language-mode]')),
  pioModeControl: $('pio-mode-control'),
  pioModeToggle: $('pio-mode-toggle'),
  pioModeState: $('pio-mode-state'),
  headModeLabel: $('head-mode-label'),
  uploadPdf: $('upload-pdf'),
  pdfUploadInput: $('pdf-upload-input'),
  queryInput: $('query-input'),
  queryStatus: $('query-status'),
  queryTiming: $('query-timing'),
  chatPane: $('chat-pane'),
  chatInner: $('chat-inner'),
  footerTime: $('footer-time'),
  promptChips: $('prompt-chips'),
  botStatusPanel: $('bot-status-panel'),
  botStatusDot: $('bot-status-dot'),
  botStatusText: $('bot-status-text'),
  stPipelineDot: document.querySelector('#st-pipeline .status-dot'),
  stPipelineVal: $('st-pipeline-val'),
  stDbDot: document.querySelector('#st-db .status-dot'),
  stDbVal: $('st-db-val'),
  stDocsDot: document.querySelector('#st-docs .status-dot'),
  stDocsVal: $('st-docs-val'),
  drawerOverlay: $('drawer-overlay'),
  sourceDrawer: $('source-drawer'),
  drawerBody: $('drawer-body'),
  drawerClose: $('drawer-close'),
  pdfPanel: $('pdf-panel'),
  pdfOverlay: $('pdf-overlay'),
  pdfIframe: $('pdf-iframe'),
  pdfTitle: $('pdf-title'),
  pdfClose: $('pdf-close'),
  pdfLoading: $('pdf-loading'),
  documentLoadingLabel: $('document-loading-label'),
  documentError: $('document-error'),
  structureContent: $('structure-content'),
  toastContainer: $('toast-container')
};

const state = {
  initialized: false,
  ocrReady: true,
  ocrModel: 'ollama',
  ocrError: '',
  loading: false,
  authenticatedUser: null,
  loginAccountType: 'citizen',
  pioMode: localStorage.getItem(PIO_MODE_KEY) === 'true',
  languageMode: normaliseLanguageMode(localStorage.getItem(LANGUAGE_MODE_KEY)),
  pdfBlobUrl: null,
  conversations: [],
  activeId: null
};

const api = {
  async request(method, path, body, requiresAuth = true) {
    const headers = { 'Content-Type': 'application/json' };
    if (requiresAuth && authToken()) headers.Authorization = `Bearer ${authToken()}`;
    const opts = { method, headers };
    if (body !== undefined) opts.body = JSON.stringify(body);

    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (requiresAuth && res.status === 401) handleUnauthorized();
    return { ok: res.ok, status: res.status, data };
  },
  async streamRequest(path, body, handlers = {}) {
    const res = await fetch(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authToken()}`
      },
      body: JSON.stringify(body || {})
    });

    if (res.status === 401) {
      handleUnauthorized();
      throw new Error('Authentication required.');
    }
    if (!res.body) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `HTTP ${res.status}`);
    }

    const decoder = new TextDecoder();
    const reader = res.body.getReader();
    let buffer = '';

    function dispatchSseFrame(frame) {
      const lines = frame.split(/\r?\n/);
      let event = 'message';
      const dataLines = [];

      lines.forEach(line => {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      });

      if (!dataLines.length) return;

      let data = {};
      try {
        data = JSON.parse(dataLines.join('\n'));
      } catch (_) {
        data = { text: dataLines.join('\n') };
      }

      if (typeof handlers[event] === 'function') handlers[event](data);
    }

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() || '';
      frames.forEach(dispatchSseFrame);
    }

    buffer += decoder.decode();
    if (buffer.trim()) dispatchSseFrame(buffer);
  },
  login: (identifier, password, accountType) =>
    api.request('POST', '/auth/login', { identifier, password, accountType }, false),
  signup: details => api.request('POST', '/auth/signup', details, false),
  session: () => api.request('GET', '/auth/session'),
  logout: () => api.request('POST', '/auth/logout'),
  health: () => api.request('GET', '/api/health'),
  init: () => api.request('POST', '/api/init'),
  dbStatus: () => api.request('GET', '/api/db-status'),
  query: (query, numResults, pioMode, answerLanguage, conversationContext = []) =>
    api.request('POST', '/api/query', {
      query,
      num_results: numResults,
      pio_mode: Boolean(pioMode),
      answer_language: normaliseLanguageMode(answerLanguage),
      conversation_context: conversationContext
    }),
  queryStream: (query, numResults, pioMode, answerLanguage, handlers, conversationContext = []) =>
    api.streamRequest('/api/query/stream', {
      query,
      num_results: numResults,
      pio_mode: Boolean(pioMode),
      answer_language: normaliseLanguageMode(answerLanguage),
      conversation_context: conversationContext
    }, handlers),
  pioPrecedents: (advisoryId, numResults = 5, answerLanguage) =>
    api.request('POST', '/api/pio/precedents', {
      advisory_id: advisoryId,
      num_results: numResults,
      answer_language: normaliseLanguageMode(answerLanguage)
    }),
  pioPrecedentsStream: (advisoryId, numResults = 5, answerLanguage, handlers) =>
    api.streamRequest('/api/pio/precedents/stream', {
      advisory_id: advisoryId,
      num_results: numResults,
      answer_language: normaliseLanguageMode(answerLanguage)
    }, handlers),
  pioPrecedentAdvisoryStream: (advisoryId, answerLanguage, handlers) =>
    api.streamRequest('/api/pio/precedent-advisory/stream', {
      advisory_id: advisoryId,
      answer_language: normaliseLanguageMode(answerLanguage)
    }, handlers),
  webVerification: advisoryId =>
    api.request('POST', '/api/web-verification/section-4', {
      advisory_id: advisoryId
    }),
  retryWebVerification: (verificationId, answerLanguage) =>
    api.request(
      'POST',
      `/api/web-verification/${encodeURIComponent(verificationId)}/retry`,
      { answer_language: normaliseLanguageMode(answerLanguage) }
    ),
  async uploadPioPdf(file, answerLanguage) {
    const body = new FormData();
    body.append('pdf', file);
    body.append('answer_language', normaliseLanguageMode(answerLanguage));

    const res = await fetch('/api/pio/upload-pdf', {
      method: 'POST',
      headers: { Authorization: `Bearer ${authToken()}` },
      body
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  },

  documentStructure: actualPdf => api.request('POST', '/api/document-structure', { actual_pdf: actualPdf }),
  async fetchPdf(path) {
    const res = await fetch(path, {
      headers: { Authorization: `Bearer ${authToken()}` }
    });
    if (!res.ok) throw new Error(t('pdfFetchFailed', { status: res.status }));
    return res.blob();
  }
};

function nowIso() {
  return new Date().toISOString();
}

function newId() {
  return `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function normaliseLanguageMode(mode) {
  return String(mode || '').toLowerCase() === 'hi' ? 'hi' : 'en';
}

function localeTag() {
  return normaliseLanguageMode(state?.languageMode) === 'hi' ? 'hi-IN' : 'en-IN';
}

function t(key, variables = {}) {
  const mode = normaliseLanguageMode(state?.languageMode);
  const template = TRANSLATIONS[mode]?.[key] ?? TRANSLATIONS.en[key] ?? key;
  return String(template).replace(/\{(\w+)\}/g, (_, name) =>
    Object.prototype.hasOwnProperty.call(variables, name) ? String(variables[name]) : `{${name}}`
  );
}

function applyTranslations() {
  const mode = normaliseLanguageMode(state.languageMode);
  document.documentElement.lang = mode;

  document.querySelectorAll('[data-i18n]').forEach(element => {
    element.textContent = t(element.dataset.i18n);
  });

  [
    ['data-i18n-aria-label', 'aria-label'],
    ['data-i18n-title', 'title'],
    ['data-i18n-placeholder', 'placeholder'],
    ['data-i18n-alt', 'alt']
  ].forEach(([dataAttribute, targetAttribute]) => {
    document.querySelectorAll(`[${dataAttribute}]`).forEach(element => {
      element.setAttribute(targetAttribute, t(element.getAttribute(dataAttribute)));
    });
  });
}

const KNOWN_UI_MESSAGE_KEYS = [
  'checkingAssistantStatus',
  'checkingBotStatus',
  'searchingDecisions',
  'generatingPrecedentAdvisory',
  'referenceSearchFailed',
  'advisoryGenerationFailed',
  'queryFailed',
  'refreshFailed',
  'refreshBot',
  'refreshing',
  'refreshingBot',
  'backendUnavailable',
  'assistantUnavailable',
  'botNeedsAttention',
  'allSystemsOperational',
  'botStatusPending',
  'checking',
  'failed',
  'offline',
  'available',
  'unavailable',
  'statusReady',
  'loadingDocument',
  'loadingPdf',
  'loadingStructure',
  'retrieving',
  'analysingRti',
  'retrievingContext',
  'generatingAnswer',
  'uploadingPdf',
  'extractingPdf',
  'ready'
];

function localizeKnownUiMessage(message, fallbackKey = '') {
  const value = String(message || '').trim();
  const key = KNOWN_UI_MESSAGE_KEYS.find(candidate =>
    Object.values(TRANSLATIONS).some(catalog => catalog[candidate] === value)
  );
  if (key) return t(key);

  const ocrMatch = value.match(/^(?:OCR unavailable|OCR उपलब्ध नहीं है) \((.+)\)$/u);
  if (ocrMatch) return t('ocrUnavailable', { model: ocrMatch[1] });

  return value || (fallbackKey ? t(fallbackKey) : '');
}

function localizeStatusRowValue(value) {
  const text = String(value || '').trim();
  if (!text || text === '-') return text;

  const pointMatch = text.match(/^(.+?)\s+(?:pts|बिंदु)$/u);
  if (pointMatch) return t('points', { count: pointMatch[1] });

  return localizeKnownUiMessage(text);
}

function answerLanguageInstruction(mode) {
  return normaliseLanguageMode(mode) === 'hi'
    ? 'Answer in Hindi using Devanagari script. Keep official names, emails, office codes, Acts, and section numbers unchanged.'
    : 'Answer in English. Keep official names, emails, office codes, Acts, and section numbers unchanged.';
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function truncate(value, max = 700) {
  const text = String(value ?? '').trim();
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function normaliseWebVerificationStatus(value) {
  const status = String(value || '').trim().toUpperCase();
  if (status === 'SEARCH_NOT_TRIGGERED') return status;
  return WEB_VERIFICATION_VISIBLE_STATUSES.has(status) ? status : '';
}

function isOfficialVerificationHostname(hostname) {
  const value = String(hostname || '').trim().toLowerCase().replace(/\.$/, '');
  return (
    value === 'gov.in' ||
    value.endsWith('.gov.in') ||
    value === 'nic.in' ||
    value.endsWith('.nic.in')
  );
}

function officialVerificationUrl(value) {
  try {
    const url = new URL(String(value || '').trim());
    if (url.protocol !== 'https:') return null;
    if (url.username || url.password) return null;
    if (url.port && url.port !== '443') return null;
    if (!isOfficialVerificationHostname(url.hostname)) return null;
    return url;
  } catch (_) {
    return null;
  }
}

function verificationValues(value) {
  const items = Array.isArray(value) ? value : value == null ? [] : [value];
  const seen = new Set();
  const values = [];

  items.forEach(item => {
    const candidate = typeof item === 'object' && item !== null
      ? item.name || item.label || item.field || item.domain || item.value || ''
      : item;
    const text = String(candidate || '').trim();
    const key = text.toLocaleLowerCase();
    if (!text || seen.has(key)) return;
    seen.add(key);
    values.push(text);
  });

  return values;
}

function officialDomainFromValue(value) {
  const directUrl = officialVerificationUrl(value);
  if (directUrl) return directUrl.hostname.toLowerCase().replace(/\.$/, '');

  try {
    const candidate = new URL(`https://${String(value || '').trim()}`);
    return isOfficialVerificationHostname(candidate.hostname)
      ? candidate.hostname.toLowerCase().replace(/\.$/, '')
      : '';
  } catch (_) {
    return '';
  }
}

function verifiedWebSources(verification) {
  const candidates = verification?.found_items
    || verification?.verified_sources
    || verification?.evidence
    || verification?.evidence_items
    || verification?.sources
    || [];
  if (!Array.isArray(candidates)) return [];

  return candidates.reduce((sources, source) => {
    if (!source || typeof source !== 'object' || source.verified !== true) {
      return sources;
    }

    const url = officialVerificationUrl(source.final_url || source.url);
    if (!url) return sources;
    sources.push({ source, url });
    return sources;
  }, []);
}

function searchedOfficialDomains(verification, sources) {
  const configured = verification?.searched_domains
    || verification?.searched_sources
    || verification?.official_domains
    || [];
  const domains = verificationValues(configured)
    .map(officialDomainFromValue)
    .filter(Boolean);
  sources.forEach(({ url }) => domains.push(url.hostname.toLowerCase().replace(/\.$/, '')));
  return [...new Set(domains)];
}

function effectiveWebVerificationStatus(verification, sources) {
  const status = normaliseWebVerificationStatus(verification?.status);
  if (['FOUND', 'PARTIALLY_FOUND'].includes(status) && !sources.length) {
    return 'SOURCE_UNAVAILABLE';
  }
  return status;
}

function formatVerificationTimestamp(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(localeTag(), {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
    timeZoneName: 'short'
  }).format(date);
}

function formatVerificationDate(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return String(value || '').trim();
  return new Intl.DateTimeFormat(localeTag(), {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'Asia/Kolkata'
  }).format(date);
}

function appendVerificationMeta(parent, label, value) {
  const text = String(value || '').trim();
  if (!text) return;

  const item = document.createElement('div');
  item.className = 'web-verification-meta-item';

  const term = document.createElement('dt');
  term.textContent = label;
  const description = document.createElement('dd');
  description.textContent = text;

  item.appendChild(term);
  item.appendChild(description);
  parent.appendChild(item);
}

function appendVerificationFields(parent, label, values, modifier) {
  const section = document.createElement('section');
  section.className = `web-verification-field-group ${modifier}`;

  const heading = document.createElement('h4');
  heading.textContent = label;
  section.appendChild(heading);

  const list = document.createElement('ul');
  const items = values.length ? values : [t('noneReported')];
  items.forEach(value => {
    const item = document.createElement('li');
    item.textContent = value;
    list.appendChild(item);
  });
  section.appendChild(list);
  parent.appendChild(section);
}

function createWebVerificationSource(item, index) {
  const { source, url } = item;
  const card = document.createElement('article');
  card.className = 'web-verification-source';

  const title = document.createElement('h4');
  title.textContent = truncate(
    source.title || source.document_title || `${t('officialSource')} ${index + 1}`,
    180
  );
  card.appendChild(title);

  const metadata = document.createElement('dl');
  metadata.className = 'web-verification-source-meta';
  appendVerificationMeta(
    metadata,
    t('publicationDate'),
    formatVerificationDate(source.publication_date || source.published_at)
  );
  appendVerificationMeta(metadata, t('pageNumber'), source.page_number);
  appendVerificationMeta(metadata, t('sectionHeading'), source.section_heading || source.section);
  if (metadata.childElementCount) card.appendChild(metadata);

  const matchedText = truncate(
    source.matched_text || source.matched_passage || source.passage || source.excerpt,
    480
  );
  if (matchedText) {
    const evidence = document.createElement('div');
    evidence.className = 'web-verification-evidence';

    const label = document.createElement('div');
    label.className = 'web-verification-evidence-label';
    label.textContent = t('matchedEvidence');

    const quote = document.createElement('blockquote');
    quote.textContent = matchedText;

    evidence.appendChild(label);
    evidence.appendChild(quote);
    card.appendChild(evidence);
  }

  const link = document.createElement('a');
  link.className = 'web-verification-source-link';
  link.href = url.href;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.textContent = t('openOfficialSource', { domain: url.hostname });
  link.setAttribute('aria-label', t('openOfficialSource', { domain: url.hostname }));
  card.appendChild(link);

  return card;
}

function createWebVerificationCard(message) {
  const verification = message?.webVerification;
  if (!verification || typeof verification !== 'object' || verification.triggered === false) {
    return null;
  }

  const sources = verifiedWebSources(verification);
  const status = effectiveWebVerificationStatus(verification, sources);
  if (!WEB_VERIFICATION_VISIBLE_STATUSES.has(status)) return null;

  const card = document.createElement('section');
  card.className = 'web-verification-card';
  card.dataset.status = status;
  card.setAttribute('role', 'region');
  card.setAttribute('aria-label', t('publicDomainVerification'));

  const header = document.createElement('div');
  header.className = 'web-verification-header';

  const title = document.createElement('h3');
  title.textContent = t('publicDomainVerification');
  header.appendChild(title);

  const statusLabel = document.createElement('span');
  statusLabel.className = 'web-verification-status';
  statusLabel.textContent = `${t('verificationStatus')}: ${t(WEB_VERIFICATION_STATUS_KEYS[status])}`;
  header.appendChild(statusLabel);
  card.appendChild(header);

  const overview = document.createElement('dl');
  overview.className = 'web-verification-overview';
  appendVerificationMeta(
    overview,
    t('officialSource'),
    t('verifiedOfficialDocuments', { count: sources.length })
  );

  const domains = searchedOfficialDomains(verification, sources);
  appendVerificationMeta(overview, t('searchedOfficialDomains'), domains.join(', '));

  const checkedAt = verification.checked_at
    || verification.verified_at
    || verification.verification_timestamp
    || verification.completed_at;
  appendVerificationMeta(overview, t('lastChecked'), formatVerificationTimestamp(checkedAt));
  card.appendChild(overview);

  const fields = document.createElement('div');
  fields.className = 'web-verification-fields';
  appendVerificationFields(
    fields,
    t('availableFields'),
    verificationValues(verification.available_fields || verification.supported_fields),
    'available'
  );
  appendVerificationFields(
    fields,
    t('missingFields'),
    verificationValues(verification.missing_fields || verification.unsupported_fields),
    'missing'
  );
  card.appendChild(fields);

  if (status === 'SOURCE_UNAVAILABLE') {
    const warning = document.createElement('p');
    warning.className = 'web-verification-warning';
    warning.textContent = t('someOfficialSourcesUnavailable');
    card.appendChild(warning);
  }

  if (sources.length) {
    const sourceList = document.createElement('div');
    sourceList.className = 'web-verification-source-list';
    sources.forEach((source, index) => {
      sourceList.appendChild(createWebVerificationSource(source, index));
    });
    card.appendChild(sourceList);
  }

  const verificationId = String(verification.verification_id || verification.id || '').trim();
  if (status === 'SOURCE_UNAVAILABLE' && verificationId) {
    const actions = document.createElement('div');
    actions.className = 'web-verification-actions';

    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'web-verification-retry';
    retry.disabled = Boolean(message.webVerificationRetrying);
    retry.textContent = message.webVerificationRetrying
      ? t('retryingVerification')
      : t('retryUnavailableSources');
    retry.addEventListener('click', () => handleWebVerificationRetry(message.id));
    actions.appendChild(retry);
    card.appendChild(actions);
  }

  return card;
}

async function handleWebVerificationRetry(messageId) {
  const conversation = activeConversation();
  const message = findConversationMessage(conversation, messageId);
  if (!message || message.webVerificationRetrying) return;

  const verification = message.webVerification;
  const sources = verifiedWebSources(verification);
  if (effectiveWebVerificationStatus(verification, sources) !== 'SOURCE_UNAVAILABLE') return;

  const verificationId = String(verification?.verification_id || verification?.id || '').trim();
  if (!verificationId) return;

  message.webVerificationRetrying = true;
  renderAll();

  try {
    const { ok, data } = await api.retryWebVerification(verificationId, state.languageMode);
    if (!ok || data?.success === false) throw new Error('verification retry failed');

    const refreshed = data?.web_verification || data?.verification || data?.result || data;
    if (!refreshed || typeof refreshed !== 'object') {
      throw new Error('invalid verification response');
    }
    const refreshedStatus = normaliseWebVerificationStatus(refreshed.status);
    if (!refreshedStatus) throw new Error('missing verification status');

    message.webVerification = refreshed;
  } catch (_) {
    toast(t('verificationRetryFailed'), 'error');
  } finally {
    message.webVerificationRetrying = false;
    touchConversation(conversation);
    renderAll();
  }
}

function loadConversations() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    state.conversations = Array.isArray(parsed) ? parsed : [];
  } catch (_) {
    state.conversations = [];
  }

  state.activeId = localStorage.getItem(ACTIVE_KEY);
  if (!state.conversations.some(c => c.id === state.activeId)) {
    const first = state.conversations[0] || createConversation(false);
    state.activeId = first.id;
  }
  saveConversations();
}

function saveConversations() {
  state.conversations.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
  state.conversations = state.conversations.slice(0, MAX_HISTORY_ITEMS);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.conversations));
  localStorage.setItem(ACTIVE_KEY, state.activeId || '');
}

function createConversation(makeActive = true) {
  const conversation = {
    id: newId(),
    title: 'New chat',
    createdAt: nowIso(),
    updatedAt: nowIso(),
    messages: []
  };
  state.conversations.unshift(conversation);
  if (makeActive) state.activeId = conversation.id;
  return conversation;
}

function activeConversation() {
  let conversation = state.conversations.find(c => c.id === state.activeId);
  if (!conversation) conversation = createConversation(true);
  return conversation;
}

function titleFrom(text) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim();
  return clean.length > 46 ? `${clean.slice(0, 46)}...` : clean || 'New chat';
}

function touchConversation(conversation) {
  conversation.updatedAt = nowIso();
  if (!conversation.title || conversation.title === 'New chat') {
    const firstUser = conversation.messages.find(m => m.role === 'user');
    if (firstUser) conversation.title = titleFrom(firstUser.display || firstUser.content);
  }
  saveConversations();
}

function renderHistory() {
  ui.historyList.innerHTML = '';

  if (!state.conversations.length) {
    const empty = document.createElement('div');
    empty.className = 'history-empty';
    empty.textContent = t('noHistory');
    ui.historyList.appendChild(empty);
    return;
  }

  state.conversations.forEach(conversation => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = `history-item${conversation.id === state.activeId ? ' active' : ''}`;
    item.innerHTML = `
      <span class="history-title">${escapeHtml(
        !conversation.title || conversation.title === 'New chat'
          ? t('newChat')
          : conversation.title
      )}</span>
      <span class="history-date">${formatHistoryDate(conversation.updatedAt)}</span>
    `;
    item.addEventListener('click', () => {
      state.activeId = conversation.id;
      saveConversations();
      renderAll();
    });
    ui.historyList.appendChild(item);
  });
}

function formatHistoryDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(localeTag(), {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}

function renderWelcome() {
  const wrap = document.createElement('div');
  wrap.className = 'welcome';
  wrap.id = 'welcome';
  wrap.innerHTML = `
    <h1>${escapeHtml(t('welcomeTitle'))}</h1>
    <p>${escapeHtml(t('welcomeDescription'))}</p>
    <div class="chips">
      ${DEFAULT_PROMPT_KEYS.map(key => `<button class="chip" type="button">${escapeHtml(t(key))}</button>`).join('')}
    </div>
  `;
  wrap.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => usePrompt(chip.textContent));
  });
  return wrap;
}

function renderMessages() {
  const conversation = activeConversation();
  ui.chatInner.innerHTML = '';

  if (!conversation.messages.length) {
    ui.chatInner.appendChild(renderWelcome());
    return;
  }

  conversation.messages.forEach(message => {
    ui.chatInner.appendChild(createMessageElement(message));
  });
  scrollChatToBottom();
}

function updateStreamingMessage(messageId, text) {
  const node = ui.chatInner.querySelector(`[data-message-id="${messageId}"]`);
  if (!node) {
    renderMessages();
    return;
  }

  const bubble = node.querySelector('.bubble');
  if (!bubble) return;

  bubble.innerHTML = '';
  const textEl = document.createElement('div');
  textEl.className = 'text streaming';
  textEl.innerHTML = formatMessageText(text);
  bubble.appendChild(textEl);
  scrollChatToBottom();
}

function createMessageElement(message) {
  const wrapper = document.createElement('article');
  wrapper.className = `msg ${message.role === 'user' ? 'user' : 'bot'}${message.pending ? ' pending' : ''}`;
  wrapper.dataset.messageId = message.id;

  const who = document.createElement('div');
  who.className = 'who';
  if (message.role === 'user') {
    who.textContent = t('you');
  } else {
    const logo = document.createElement('img');
    logo.src = CG_GOV_LOGO;
    logo.alt = t('cgGovernmentLogo');
    logo.loading = 'lazy';
    who.appendChild(logo);
  }

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  const visibleText = message.display || message.content || '';

  if (message.pending && !visibleText) {
    bubble.innerHTML = '<div class="dots"><span></span><span></span><span></span></div>';
  } else {
    const text = document.createElement('div');
    text.className = 'text';
    text.innerHTML = formatMessageText(visibleText);
    bubble.appendChild(text);

    if (!message.pending && message.role === 'assistant' && message.webVerification) {
      const verificationCard = createWebVerificationCard(message);
      if (verificationCard) bubble.appendChild(verificationCard);
    }

    if (!message.pending && message.role === 'assistant' && message.pioDetails) {
      bubble.appendChild(createPioAnalysisDetails(message.pioDetails));
    }

    if (
      !message.pending &&
      message.role === 'assistant' &&
      (message.precedentSearchAvailable || message.webSearchAvailable)
    ) {
      bubble.appendChild(createPrecedentActionControls(message));
    }

    if (!message.pending && message.role === 'assistant' && message.timing) {
      const meta = document.createElement('div');
      meta.className = 'message-meta';
      meta.textContent = t('answeredIn', { time: message.timing });
      bubble.appendChild(meta);
    }

    if (!message.pending && message.role === 'assistant' && message.results?.length) {
      const btn = document.createElement('button');
      btn.className = 'sources-btn';
      btn.type = 'button';
      btn.innerHTML = `<span class="source-count">${message.results.length}</span> ${escapeHtml(t('viewSources'))}`;
      btn.addEventListener('click', () => openDrawer(message.results));
      bubble.appendChild(btn);
    }
  }

  if (message.role === 'user') {
    wrapper.appendChild(bubble);
    wrapper.appendChild(who);
  } else {
    wrapper.appendChild(who);
    wrapper.appendChild(bubble);
  }

  return wrapper;
}

function formatMessageText(text) {
  const raw = String(text ?? '').trim();
  if (!raw) return '';

  const html = [];
  let paragraph = [];

  const inlineMarkdown = value =>
    escapeHtml(value).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${paragraph.join('<br>')}</p>`);
    paragraph = [];
  };

  raw.split(/\r?\n/).forEach(line => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      return;
    }

    const heading = trimmed.match(/^###\s+(.+)$/);
    if (heading) {
      flushParagraph();
      html.push(`<h3>${inlineMarkdown(heading[1])}</h3>`);
      return;
    }

    paragraph.push(inlineMarkdown(trimmed));
  });

  flushParagraph();
  return html.join('');
}

function buildPioDetails(data) {
  if (!data || !(data.pio_pipeline_used || data.route === 'PIO_ADVISORY')) {
    return null;
  }

  return {
    rtiExtraction: data.rti_extraction || null,
    legalAnalysis: data.legal_analysis || null,
    appliedProvisions: data.validation?.call_3_cited_provisions || [],
    validation: data.validation || null
  };
}

function createPioAnalysisDetails(details) {
  const outer = document.createElement('details');
  outer.className = 'analysis-details';

  const summary = document.createElement('summary');
  summary.textContent = t('analysisDetails');
  outer.appendChild(summary);

  const sections = [
    [t('rtiExtraction'), details.rtiExtraction],
    [t('legalAnalysis'), details.legalAnalysis],
    [t('appliedProvisions'), details.appliedProvisions],
    [t('validationResult'), details.validation]
  ];

  sections.forEach(([title, value]) => {
    const section = document.createElement('details');
    section.className = 'analysis-detail-section';

    const sectionSummary = document.createElement('summary');
    sectionSummary.textContent = title;

    const pre = document.createElement('pre');
    pre.textContent = value == null
      ? '-'
      : typeof value === 'string'
        ? value
        : JSON.stringify(value, null, 2);

    section.appendChild(sectionSummary);
    section.appendChild(pre);
    outer.appendChild(section);
  });

  return outer;
}

function createPrecedentReferencesDropdown(message) {
  const results = Array.isArray(message.precedentResults)
    ? message.precedentResults
    : [];
  const details = document.createElement('details');
  details.className = 'precedent-reference-details';

  const summary = document.createElement('summary');
  summary.textContent = t('decisionReferences', { count: results.length });
  details.appendChild(summary);

  if (message.precedentReferenceNote) {
    const note = document.createElement('div');
    note.className = 'precedent-reference-note';
    note.innerHTML = formatMessageText(message.precedentReferenceNote);
    details.appendChild(note);
  }

  if (results.length) {
    const sourceList = createPrecedentPdfLinks(results);
    details.appendChild(sourceList);
  } else {
    const empty = document.createElement('p');
    empty.className = 'precedent-reference-empty';
    empty.textContent = t('noDecisionReferences');
    details.appendChild(empty);
  }

  return details;
}

function normalizePdfFilename(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const filename = raw.replace(/\\/g, '/').split('/').pop().trim();
  if (!filename) return '';
  return filename.toLowerCase().endsWith('.pdf') ? filename : `${filename}.pdf`;
}

function precedentPdfFilename(result) {
  const verification = result.case_verification || {};
  return normalizePdfFilename(
    verification.source_file ||
    result.actual_pdf ||
    result.decision_pdf ||
    result.source ||
    result.document_id
  );
}

function createPrecedentPdfLinks(results) {
  const sourceList = document.createElement('div');
  sourceList.className = 'precedent-pdf-links';

  const seen = new Set();
  const filenames = [];
  results.forEach(result => {
    const filename = precedentPdfFilename(result);
    const key = filename.toLowerCase();
    if (!filename || seen.has(key)) return;
    seen.add(key);
    filenames.push(filename);
  });

  if (!filenames.length) {
    const empty = document.createElement('p');
    empty.className = 'precedent-reference-empty';
    empty.textContent = t('noSourcePdfName');
    sourceList.appendChild(empty);
    return sourceList;
  }

  filenames.forEach(filename => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'precedent-pdf-link';
    button.title = t('openFile', { filename });
    button.innerHTML = `
      <span aria-hidden="true" class="precedent-pdf-icon">PDF</span>
      <span>${escapeHtml(filename)}</span>
    `;
    button.addEventListener('click', () => openPdfPanel(filename));
    sourceList.appendChild(button);
  });

  return sourceList;
}

function createPrecedentActionControls(message) {
  const container = document.createElement('div');
  container.className = 'precedent-actions';

  const decision = message.precedentDecision || 'pending';

  const appendWebButton = buttonRow => {
    if (!message.webSearchAvailable) return;
    const webButton = document.createElement('button');
    webButton.type = 'button';
    webButton.className = 'precedent-action-btn secondary web-search-action-btn';
    webButton.textContent = message.webSearchInProgress
      ? t('searchingOfficialWeb')
      : t('searchOfficialWeb');
    webButton.disabled = state.loading || message.webSearchInProgress;
    webButton.addEventListener('click', () => handleWebSearch(message.id));
    buttonRow.appendChild(webButton);
  };

  if (decision === 'completed') {
    container.appendChild(createPrecedentReferencesDropdown(message));

    const buttonRow = document.createElement('div');
    buttonRow.className = 'precedent-action-buttons';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'precedent-action-btn';

    if (message.precedentAdvisoryStatus === 'generating') {
      button.textContent = t('generatingPrecedentAdvisory');
      button.disabled = true;
    } else if (message.precedentAdvisoryGenerated) {
      button.textContent = t('precedentAdvisoryGenerated');
      button.disabled = true;
    } else {
      button.textContent = t('generatePrecedentAdvisory');
      button.disabled = state.loading;
      button.addEventListener('click', () => {
        handleGeneratePrecedentAdvisory(message.id);
      });
    }

    buttonRow.appendChild(button);
    appendWebButton(buttonRow);
    container.appendChild(buttonRow);
    return container;
  }

  if (decision === 'declined') {
    container.innerHTML = `<span class="precedent-status">${escapeHtml(t('referencesNotAdded'))}</span>`;
    const buttonRow = document.createElement('div');
    buttonRow.className = 'precedent-action-buttons';
    appendWebButton(buttonRow);
    container.appendChild(buttonRow);
    return container;
  }

  if (decision === 'accepted') {
    container.innerHTML = `<span class="precedent-status">${escapeHtml(t('searchingDecisions'))}</span>`;
    const buttonRow = document.createElement('div');
    buttonRow.className = 'precedent-action-buttons';
    appendWebButton(buttonRow);
    container.appendChild(buttonRow);
    return container;
  }

  const label = document.createElement('div');
  label.className = 'precedent-action-label';
  label.textContent = t('addSupportingReferences');
  container.appendChild(label);

  const buttonRow = document.createElement('div');
  buttonRow.className = 'precedent-action-buttons';

  const yesButton = document.createElement('button');
  yesButton.type = 'button';
  yesButton.className = 'precedent-action-btn';
  yesButton.textContent = t('yesAddReferences');
  yesButton.addEventListener('click', () => {
    handlePrecedentChoice(message.id, 'yes', t('yesAddReferencesMessage'));
  });

  const noButton = document.createElement('button');
  noButton.type = 'button';
  noButton.className = 'precedent-action-btn secondary';
  noButton.textContent = t('no');
  noButton.addEventListener('click', () => {
    handlePrecedentChoice(message.id, 'no', t('no'));
  });

  buttonRow.appendChild(yesButton);
  buttonRow.appendChild(noButton);
  appendWebButton(buttonRow);
  container.appendChild(buttonRow);
  return container;
}

async function handleWebSearch(advisoryMessageId) {
  const conversation = activeConversation();
  const advisoryMessage = findConversationMessage(conversation, advisoryMessageId);
  if (!advisoryMessage || state.loading || !advisoryMessage.advisoryId) return;

  advisoryMessage.webSearchInProgress = true;
  state.loading = true;
  disableQueryBar(t('searchingOfficialWeb'));
  touchConversation(conversation);
  renderAll();

  try {
    const { ok, data } = await api.webVerification(advisoryMessage.advisoryId);
    if (!ok || data?.success === false) {
      throw new Error(data?.error || t('officialWebSearchFailed'));
    }
    advisoryMessage.webVerification = data;
    advisoryMessage.webSearchAvailable = false;
  } catch (error) {
    toast(error.message || t('officialWebSearchFailed'), 'error');
  } finally {
    advisoryMessage.webSearchInProgress = false;
    state.loading = false;
    enableQueryBar();
    touchConversation(conversation);
    renderAll();
    updateFooterTime();
  }
}

function normaliseConfirmation(text) {
  return String(text || '')
    .trim()
    .toLocaleLowerCase()
    .replace(/[.!?]/g, '');
}

function isPrecedentYes(text) {
  return PRECEDENT_YES_CONFIRMATIONS.has(normaliseConfirmation(text));
}

function isPrecedentNo(text) {
  return PRECEDENT_NO_CONFIRMATIONS.has(normaliseConfirmation(text));
}

function findConversationMessage(conversation, messageId) {
  return conversation.messages.find(message => message.id === messageId) || null;
}

function getPendingPrecedentOffer(conversation) {
  const latestVisible = [...conversation.messages]
    .reverse()
    .find(message => !message.pending);

  if (!latestVisible) return null;
  if (
    latestVisible.role !== 'assistant' ||
    !latestVisible.precedentSearchAvailable ||
    !latestVisible.advisoryId ||
    (latestVisible.precedentDecision || 'pending') !== 'pending'
  ) {
    return null;
  }

  return latestVisible;
}

function appendUserChoice(conversation, text) {
  const message = {
    id: newId(),
    role: 'user',
    content: text,
    display: text,
    createdAt: nowIso()
  };
  conversation.messages.push(message);
  return message;
}

async function handlePrecedentChoice(advisoryMessageId, choice, displayText) {
  const conversation = activeConversation();
  const advisoryMessage = findConversationMessage(conversation, advisoryMessageId);
  if (!advisoryMessage || state.loading) return;

  if (choice === 'no') {
    advisoryMessage.precedentDecision = 'declined';
    appendUserChoice(conversation, displayText || t('no'));
    conversation.messages.push({
      id: newId(),
      role: 'assistant',
      content: t('referencesNotAdded'),
      display: t('referencesNotAdded'),
      createdAt: nowIso()
    });
    touchConversation(conversation);
    renderAll();
    return;
  }

  if (!advisoryMessage.advisoryId) {
    toast(t('advisoryNotLinkable'), 'error');
    return;
  }

  advisoryMessage.precedentDecision = 'accepted';
  state.loading = true;
  disableQueryBar(t('searchingDecisions'));
  touchConversation(conversation);
  renderAll();

  try {
    let finalData = null;
    let streamError = null;

    await api.pioPrecedentsStream(advisoryMessage.advisoryId, 5, state.languageMode, {
      status(data) {
        disableQueryBar(localizeKnownUiMessage(data.message, 'searchingDecisions'));
      },
      done(data) {
        finalData = data;
      },
      error(data) {
        streamError = data.error || t('referenceSearchFailed');
      }
    });

    if (streamError) throw new Error(streamError);

    const data = finalData || {};
    advisoryMessage.precedentDecision = 'completed';
    advisoryMessage.precedentSearchCompleted = true;
    advisoryMessage.precedentResults = data.results || [];
    advisoryMessage.precedentReferenceNote = data.answer || '';
    advisoryMessage.precedentCollectionsUsed = data.precedent_collections_used || [];
    advisoryMessage.precedentTiming = data.execution_time || '';
    if (Array.isArray(data.warnings) && data.warnings.length) {
      toast(data.warnings.join(' | '), 'info', 5000);
    }
    ui.queryTiming.textContent = data.execution_time || '';
  } catch (error) {
    advisoryMessage.precedentDecision = 'pending';
    toast(error.message || t('networkRetrievingReferences'), 'error');
  } finally {
    state.loading = false;
    enableQueryBar();
    touchConversation(conversation);
    renderAll();
    updateFooterTime();
  }
}

async function handleGeneratePrecedentAdvisory(advisoryMessageId) {
  const conversation = activeConversation();
  const advisoryMessage = findConversationMessage(conversation, advisoryMessageId);
  if (!advisoryMessage || state.loading) return;

  if (!advisoryMessage.advisoryId || !advisoryMessage.precedentSearchCompleted) {
    toast(t('generateReferencesFirst'), 'error');
    return;
  }

  advisoryMessage.precedentAdvisoryStatus = 'generating';

  const pendingMessage = {
    id: newId(),
    role: 'assistant',
    content: '',
    pending: true,
    createdAt: nowIso()
  };

  conversation.messages.push(pendingMessage);
  state.loading = true;
  disableQueryBar(t('generatingPrecedentAdvisory'));
  touchConversation(conversation);
  renderAll();

  try {
    let finalData = null;
    let streamError = null;
    let streamedAnswer = '';

    await api.pioPrecedentAdvisoryStream(advisoryMessage.advisoryId, state.languageMode, {
      status(data) {
        disableQueryBar(localizeKnownUiMessage(data.message, 'generatingPrecedentAdvisory'));
      },
      token(data) {
        const chunk = String(data.text || '');
        if (!chunk) return;

        streamedAnswer += chunk;
        const index = conversation.messages.findIndex(message => message.id === pendingMessage.id);
        if (index >= 0) {
          conversation.messages[index] = {
            ...conversation.messages[index],
            content: streamedAnswer,
            display: streamedAnswer,
            pending: true
          };
          updateStreamingMessage(pendingMessage.id, streamedAnswer);
        }
      },
      done(data) {
        finalData = data;
      },
      error(data) {
        streamError = data.error || t('advisoryGenerationFailed');
      }
    });

    if (streamError) throw new Error(streamError);

    const data = finalData || {};
    const index = conversation.messages.findIndex(message => message.id === pendingMessage.id);
    if (index >= 0) {
      const answer = data.answer || streamedAnswer || '';
      conversation.messages[index] = {
        id: pendingMessage.id,
        role: 'assistant',
        content: answer,
        display: answer,
        results: data.results || advisoryMessage.precedentResults || [],
        timing: data.execution_time || '',
        isPrecedentAdvisory: true,
        sourceAdvisoryId: advisoryMessage.advisoryId,
        createdAt: nowIso()
      };
    }

    advisoryMessage.precedentAdvisoryStatus = 'generated';
    advisoryMessage.precedentAdvisoryGenerated = true;
    ui.queryTiming.textContent = data.execution_time || '';
  } catch (error) {
    const index = conversation.messages.findIndex(message => message.id === pendingMessage.id);
    if (index >= 0) {
      conversation.messages[index] = {
        id: pendingMessage.id,
        role: 'assistant',
        content: error.message || t('networkGeneratingAdvisory'),
        display: t('unableGenerateAdvisory', { error: error.message || t('networkError') }),
        createdAt: nowIso()
      };
    }
    advisoryMessage.precedentAdvisoryStatus = null;
    toast(error.message || t('networkGeneratingAdvisory'), 'error');
  } finally {
    state.loading = false;
    enableQueryBar();
    touchConversation(conversation);
    renderAll();
    updateFooterTime();
  }
}

function renderAll() {
  renderHistory();
  renderMessages();
}

function scrollChatToBottom() {
  requestAnimationFrame(() => {
    ui.chatPane.scrollTop = ui.chatPane.scrollHeight;
  });
}

function usePrompt(prompt) {
  ui.queryInput.value = prompt;
  autoResize();
  ui.queryInput.focus();
}

function updatePioModeUi() {
  const pioAccess = state.authenticatedUser?.role === 'pio';
  ui.pioModeControl.classList.toggle('hidden', !pioAccess);
  if (!pioAccess) state.pioMode = false;
  ui.pioModeToggle.checked = state.pioMode;
  ui.pioModeState.textContent = state.pioMode ? t('on') : t('off');
  ui.headModeLabel.textContent = state.pioMode
    ? t('pioAdvisoryEnabled')
    : t('publicGuidance');
  ui.queryInput.placeholder = state.pioMode
    ? t('pioQueryPlaceholder')
    : t('defaultQueryPlaceholder');
}

function setPioMode(enabled) {
  state.pioMode = state.authenticatedUser?.role === 'pio' && Boolean(enabled);
  localStorage.setItem(PIO_MODE_KEY, state.pioMode ? 'true' : 'false');
  updatePioModeUi();
}

function updateLanguageModeUi() {
  const mode = normaliseLanguageMode(state.languageMode);
  state.languageMode = mode;

  ui.languageOptions.forEach(button => {
    const active = button.dataset.languageMode === mode;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });

  [ui.stPipelineVal, ui.stDbVal, ui.stDocsVal].forEach(statusValue => {
    statusValue.textContent = localizeStatusRowValue(statusValue.textContent);
  });
}

function setLanguageMode(mode) {
  const currentDynamicText = {
    queryStatus: ui.queryStatus.textContent,
    botStatus: ui.botStatusText.textContent,
    refreshButton: ui.btnInit.textContent,
    documentLoading: ui.documentLoadingLabel.textContent
  };

  state.languageMode = normaliseLanguageMode(mode);
  localStorage.setItem(LANGUAGE_MODE_KEY, state.languageMode);
  updateLanguageModeUi();
  applyTranslations();
  ui.queryStatus.textContent = localizeKnownUiMessage(currentDynamicText.queryStatus, 'checkingAssistantStatus');
  ui.botStatusText.textContent = localizeKnownUiMessage(currentDynamicText.botStatus, 'checkingBotStatus');
  ui.btnInit.textContent = localizeKnownUiMessage(currentDynamicText.refreshButton, 'refreshBot');
  ui.documentLoadingLabel.textContent = localizeKnownUiMessage(currentDynamicText.documentLoading, 'loadingDocument');
  updatePioModeUi();
  renderAll();
  updateFooterTime();
}

function autoResize() {
  ui.queryInput.style.height = 'auto';
  ui.queryInput.style.height = `${Math.min(ui.queryInput.scrollHeight, 160)}px`;
}

function setStatusRow(dot, val, stateValue, text) {
  dot.dataset.state = stateValue;
  val.textContent = text;
}

function setBotStatus(stateValue, text) {
  ui.botStatusPanel.dataset.state = stateValue;
  ui.botStatusDot.dataset.state = stateValue;
  ui.botStatusText.textContent = text;
}

function setAllStatus(ps, pt, ds, dt, qs, qt) {
  setStatusRow(ui.stPipelineDot, ui.stPipelineVal, ps, pt);
  setStatusRow(ui.stDbDot, ui.stDbVal, ds, dt);
  setStatusRow(ui.stDocsDot, ui.stDocsVal, qs, qt);

  const states = [ps, ds, qs];
  if (states.includes('loading')) {
    setBotStatus('loading', t('checkingBotStatus'));
  } else if (states.includes('error')) {
    setBotStatus('error', t('botNeedsAttention'));
  } else if (!state.ocrReady) {
    setBotStatus('error', t('ocrUnavailable', { model: state.ocrModel }));
  } else if (states.every(state => state === 'ok')) {
    setBotStatus('ok', t('allSystemsOperational'));
  } else {
    setBotStatus('loading', t('botStatusPending'));
  }
}

function updateFooterTime() {
  const now = new Date();
  ui.footerTime.textContent = now.toLocaleTimeString(localeTag(), {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  });
}

function enableQueryBar(message = t('ready')) {
  ui.btnSend.disabled = false;
  if (ui.uploadPdf) ui.uploadPdf.disabled = false;
  ui.queryStatus.textContent = message;
}

function disableQueryBar(message = t('loading')) {
  ui.btnSend.disabled = true;
  if (ui.uploadPdf) ui.uploadPdf.disabled = true;
  ui.queryStatus.textContent = message;
}

async function initPipeline() {
  ui.btnInit.disabled = true;
  ui.btnInit.textContent = t('refreshing');
  disableQueryBar(t('refreshingBot'));
  setAllStatus('loading', t('checking'), 'loading', t('checking'), 'loading', t('checking'));

  try {
    const { ok, data } = await api.init();
    if (ok && data.success) {
      state.initialized = true;
      toast(t('botRefreshed'), 'success');
      await refreshDbStatus();
      enableQueryBar();
    } else {
      setAllStatus('error', t('failed'), 'error', '-', 'error', '-');
      disableQueryBar(t('refreshBeforeAsking'));
      toast(data.error || t('refreshFailed'), 'error', 5000);
    }
  } catch (err) {
    setAllStatus('error', t('offline'), 'error', '-', 'error', '-');
    disableQueryBar(t('backendUnavailable'));
    toast(t('cannotReachBackend'), 'error');
  } finally {
    ui.btnInit.disabled = false;
    ui.btnInit.textContent = t('refreshBot');
    updateFooterTime();
  }
}

async function refreshDbStatus() {
  try {
    const { ok, data } = await api.dbStatus();
    if (!ok) throw new Error(data.error || t('dbStatusFailed'));

    const dbReady = data.db_connected && data.collection_exists;
    const count = data.points_count ?? 0;
    setAllStatus(
      dbReady || state.initialized ? 'ok' : 'idle',
      dbReady || state.initialized ? t('statusReady') : '-',
      data.db_connected ? 'ok' : 'error',
      data.db_connected ? t('statusReady') : t('offline'),
      data.db_connected ? 'ok' : 'idle',
      data.db_connected ? t('points', { count: count.toLocaleString(localeTag()) }) : '-'
    );

    if (dbReady || state.initialized) enableQueryBar();
    else disableQueryBar(t('refreshBeforeAsking'));
  } catch (_) {
    setAllStatus('error', t('offline'), 'error', '-', 'error', '-');
    disableQueryBar(t('backendUnavailable'));
  }
  updateFooterTime();
}

async function bootStatus() {
  try {
    const { ok, data } = await api.health();
    if (ok && data.rag_pipeline === 'available') {
      state.initialized = Boolean(data.pipeline_initialized);
      state.ocrReady = data.ocr_ready !== false;
      state.ocrModel = String(data.ocr_model || 'ollama');
      state.ocrError = String(data.ocr_error || '');
      ui.botStatusPanel.title = state.ocrError;
      await refreshDbStatus();
      if (state.initialized) enableQueryBar();
    } else {
      setAllStatus('error', t('unavailable'), 'idle', '-', 'idle', '-');
      disableQueryBar(t('assistantUnavailable'));
    }
  } catch (_) {
    setAllStatus('error', t('offline'), 'error', '-', 'error', '-');
    disableQueryBar(t('backendUnavailable'));
  }
}

function buildConversationContext(conversation) {
  return conversation.messages
    .filter(message => (
      !message.pending &&
      (message.role === 'user' || message.role === 'assistant')
    ))
    .slice(-MAX_CONVERSATION_CONTEXT_MESSAGES)
    .map(message => ({
      role: message.role,
      content: truncate(
        String(message.content || message.display || ''),
        MAX_CONVERSATION_CONTEXT_MESSAGE_CHARS
      ).trim()
    }))
    .filter(message => message.content);
}


function buildAssistantResponseMessage(messageId, data, fallbackAnswer = '') {
  const answer = data.answer || data.pio_advisory_report || fallbackAnswer || '';
  return {
    id: messageId,
    role: 'assistant',
    content: answer,
    display: answer,
    results: data.results || [],
    webVerification: data.web_verification || null,
    pioDetails: buildPioDetails(data),
    advisoryId: data.advisory_id || null,
    webSearchAvailable: Boolean(data.advisory_id),
    precedentSearchAvailable: Boolean(
      data.precedent_search_available && data.advisory_id
    ),
    precedentDecision: (
      data.precedent_search_available && data.advisory_id
        ? 'pending'
        : null
    ),
    precedentSearchCompleted: Boolean(data.precedent_search_completed),
    timing: data.execution_time || '',
    uploadMeta: data.source_pdf
      ? {
          sourcePdf: data.source_pdf,
          structuredMdPath: data.structured_md_path || '',
          extractedMarkdownChars: data.extracted_markdown_chars || 0
        }
      : null,
    createdAt: nowIso()
  };
}



async function sendQuery() {
  const text = ui.queryInput.value.trim();
  if (!text || state.loading) return;

  const conversation = activeConversation();
  const conversationContext = buildConversationContext(conversation);
  const pendingOffer = getPendingPrecedentOffer(conversation);
  if (pendingOffer && isPrecedentYes(text)) {
    ui.queryInput.value = '';
    autoResize();
    await handlePrecedentChoice(
      pendingOffer.id,
      'yes',
      text
    );
    return;
  }
  if (pendingOffer && isPrecedentNo(text)) {
    ui.queryInput.value = '';
    autoResize();
    await handlePrecedentChoice(
      pendingOffer.id,
      'no',
      text
    );
    return;
  }

  const userMessage = {
    id: newId(),
    role: 'user',
    content: text,
    display: text,
    createdAt: nowIso()
  };
  conversation.messages.push(userMessage);
  touchConversation(conversation);

  ui.queryInput.value = '';
  autoResize();
  ui.queryTiming.textContent = '';

  const pendingMessage = {
    id: newId(),
    role: 'assistant',
    content: '',
    pending: true,
    createdAt: nowIso()
  };
  conversation.messages.push(pendingMessage);
  state.loading = true;
  disableQueryBar(t('retrieving'));
  renderAll();

  try {
    let finalData = null;
    let streamError = null;
    let streamedAnswer = '';

    await api.queryStream(
      text,
      5,
      state.pioMode,
      state.languageMode,
      {
        status(data) {
          if (data.message) disableQueryBar(localizeKnownUiMessage(data.message));
        },
        token(data) {
          const chunk = String(data.text || '');
          if (!chunk) return;

          streamedAnswer += chunk;
          const index = conversation.messages.findIndex(m => m.id === pendingMessage.id);
          if (index >= 0) {
            conversation.messages[index] = {
              ...conversation.messages[index],
              content: streamedAnswer,
              display: streamedAnswer,
              pending: true
            };
            updateStreamingMessage(pendingMessage.id, streamedAnswer);
          }
        },
        done(data) {
          finalData = data;
        },
        error(data) {
          streamError = data.error || t('queryFailed');
        }
      },
      conversationContext
    );

    const index = conversation.messages.findIndex(m => m.id === pendingMessage.id);
    if (index < 0) return;

    if (streamError) throw new Error(streamError);

    const data = finalData || {};

    if (data.success) {
      conversation.messages[index] = buildAssistantResponseMessage(
        pendingMessage.id,
        data,
        streamedAnswer
      );
      ui.queryTiming.textContent = data.execution_time || '';
    } else {
      const errorMessage = data.error || t('queryFailed');
      conversation.messages[index] = {
        id: pendingMessage.id,
        role: 'assistant',
        content: errorMessage,
        display: t('unableToAnswer', { error: errorMessage }),
        createdAt: nowIso()
      };
      toast(errorMessage, 'error');
    }
  } catch (err) {
    const index = conversation.messages.findIndex(m => m.id === pendingMessage.id);
    const errorMessage = err && err.message
      ? err.message
      : t('backendNetworkError');
    if (index >= 0) {
      conversation.messages[index] = {
        id: pendingMessage.id,
        role: 'assistant',
        content: errorMessage,
        display: t('unableToAnswer', { error: errorMessage }),
        createdAt: nowIso()
      };
    }
    toast(errorMessage, 'error');
  } finally {
    state.loading = false;
    enableQueryBar();
    touchConversation(conversation);
    renderAll();
    updateFooterTime();
  }
}

async function handlePdfUpload(event) {
  const file = event.target.files && event.target.files[0];
  event.target.value = '';

  if (!file || state.loading) return;
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    toast(t('pleaseUploadPdf'), 'error');
    return;
  }

  const conversation = activeConversation();
  const displayName = t('uploadedPdf', { filename: file.name });
  const userMessage = {
    id: newId(),
    role: 'user',
    content: displayName,
    display: displayName,
    createdAt: nowIso()
  };
  conversation.messages.push(userMessage);
  touchConversation(conversation);

  const pendingMessage = {
    id: newId(),
    role: 'assistant',
    content: '',
    pending: true,
    createdAt: nowIso()
  };
  conversation.messages.push(pendingMessage);
  state.loading = true;
  ui.queryTiming.textContent = '';
  disableQueryBar(t('uploadingPdf'));
  renderAll();

  try {
    disableQueryBar(t('extractingPdf'));
    const { ok, status, data } = await api.uploadPioPdf(file, state.languageMode);
    const index = conversation.messages.findIndex(m => m.id === pendingMessage.id);
    if (index < 0) return;

    if (ok && data.success) {
      conversation.messages[index] = buildAssistantResponseMessage(
        pendingMessage.id,
        data
      );
      ui.queryTiming.textContent = data.execution_time || '';
      toast(t('pdfProcessed'), 'success');
    } else {
      const errorMessage = data.error || t('uploadFailed', { status });
      conversation.messages[index] = {
        id: pendingMessage.id,
        role: 'assistant',
        content: errorMessage,
        display: t('unableProcessPdf', { error: errorMessage }),
        createdAt: nowIso()
      };
      toast(errorMessage, 'error');
    }
  } catch (err) {
    const index = conversation.messages.findIndex(m => m.id === pendingMessage.id);
    const errorMessage = err && err.message
      ? err.message
      : t('networkUploadingPdf');
    if (index >= 0) {
      conversation.messages[index] = {
        id: pendingMessage.id,
        role: 'assistant',
        content: errorMessage,
        display: t('unableProcessPdf', { error: errorMessage }),
        createdAt: nowIso()
      };
    }
    toast(errorMessage, 'error');
  } finally {
    state.loading = false;
    enableQueryBar();
    touchConversation(conversation);
    renderAll();
    updateFooterTime();
  }
}

function legalChunkLabel(chunkType) {
  const labels = {
    INFORMATION_REQUESTED: t('informationRequested'),
    COMMISSION_OBSERVATIONS: t('commissionObservation'),
    COMMISSION_FINDINGS: t('commissionFinding'),
    FINAL_ORDER: t('finalOrder'),
    PIO_LEARNING_SIGNAL: t('pioLearning'),
    PRECEDENT_SUMMARY: t('precedentSummary'),
    GROUNDS_FOR_APPEAL: t('groundsForAppeal'),
    HEARING_SUBMISSIONS: t('hearingSubmissions'),
    CASE_METADATA: t('caseMetadata')
  };
  return labels[chunkType] || t('relevantPassage');
}

function isOfficerDirectoryResult(result) {
  return [
    'postgresql_officer_registry',
    'pio_directory_qdrant'
  ].includes(result.retrieval_collection);
}

function openDrawer(results) {
  ui.drawerBody.innerHTML = '';

  results.forEach(result => {
    const card = document.createElement('div');
    card.className = 'source-card';

    const score = typeof result.score === 'number' ? result.score.toFixed(3) : '-';

    if (isOfficerDirectoryResult(result)) {
      const sourceLabel = result.retrieval_collection === 'pio_directory_qdrant'
        ? t('officerDirectory')
        : t('officerRegistry');

      const officerRows = [
        [t('role'), result.rti_role],
        [t('officer'), result.officer_name],
        [t('designation'), result.designation],
        [t('department'), result.department_name],
        [t('district'), result.district_name],
        [t('office'), result.office_name],
        [t('officeCode'), result.office_code],
        [t('email'), result.email],
        [t('address'), result.office_address]
      ].filter(([, value]) => String(value || '').trim());

      card.innerHTML = `
        <div class="source-card-header">
          <span class="source-rank">#${escapeHtml(result.rank || '')}</span>
          <span class="source-filename">${escapeHtml(sourceLabel)}</span>
          <span class="source-score">${score}</span>
        </div>
        <div class="source-label">${escapeHtml(t('officerDirectoryRecord'))}</div>
        <div class="officer-source-fields">
          ${officerRows.map(([label, value]) => `
            <div class="officer-source-row">
              <span>${escapeHtml(label)}</span>
              <strong>${escapeHtml(value)}</strong>
            </div>
          `).join('')}
        </div>
      `;

      ui.drawerBody.appendChild(card);
      return;
    }

    const fname = result.actual_pdf || result.source || t('unknown');
    const chunkType = result.chunk_type || '';
    const passage = result.text || result.excerpt || '';
    const metaParts = [
      result.case_number ? escapeHtml(t('case', { value: result.case_number })) : '',
      result.public_authority ? escapeHtml(t('authority', { value: result.public_authority })) : '',
      result.hearing_date ? escapeHtml(t('hearing', { value: result.hearing_date })) : '',
      result.outcome ? escapeHtml(t('outcome', { value: result.outcome })) : ''
    ].filter(Boolean);

    card.innerHTML = `
      <div class="source-card-header">
        <span class="source-rank">#${escapeHtml(result.rank || '')}</span>
        <span class="source-filename">${escapeHtml(fname)}</span>
        <span class="source-score">${score}</span>
      </div>
      ${metaParts.length ? `<div class="source-meta">${metaParts.join(' | ')}</div>` : ''}
      <div class="source-label">${escapeHtml(legalChunkLabel(chunkType))}${chunkType ? ` <span>${escapeHtml(chunkType)}</span>` : ''}</div>
      <details class="source-passage" ${passage.length < 700 ? 'open' : ''}>
        <summary>${escapeHtml(passage.length > 700 ? t('expandPassage') : t('passage'))}</summary>
        <div>${escapeHtml(passage)}</div>
      </details>
    `;

    const actionRow = document.createElement('div');
    actionRow.className = 'source-actions';

    const pdfBtn = document.createElement('button');
    pdfBtn.className = 'pdf-open-btn';
    pdfBtn.type = 'button';
    pdfBtn.textContent = t('viewPdf');
    pdfBtn.addEventListener('click', () => openPdfPanel(fname));
    actionRow.appendChild(pdfBtn);

    const structureBtn = document.createElement('button');
    structureBtn.className = 'structure-open-btn';
    structureBtn.type = 'button';
    structureBtn.textContent = t('viewStructure');
    structureBtn.disabled = result.structured_md_available === false;
    structureBtn.title = structureBtn.disabled
      ? t('structureUnavailable')
      : t('openMarkdown');
    structureBtn.addEventListener('click', () => openStructurePanel(fname));
    actionRow.appendChild(structureBtn);

    card.appendChild(actionRow);
    ui.drawerBody.appendChild(card);
  });

  ui.drawerOverlay.classList.remove('hidden');
  ui.sourceDrawer.classList.remove('hidden');
}

function closeDrawer() {
  ui.drawerOverlay.classList.add('hidden');
  ui.sourceDrawer.classList.add('hidden');
}

async function openPdfPanel(fname) {
  ui.pdfTitle.textContent = fname;
  ui.pdfIframe.src = '';
  ui.structureContent.textContent = '';
  ui.structureContent.classList.add('hidden');
  ui.documentError.textContent = '';
  ui.documentError.classList.add('hidden');
  ui.documentLoadingLabel.textContent = t('loadingPdf');
  ui.pdfLoading.classList.remove('hidden');
  ui.pdfIframe.classList.add('hidden');
  ui.pdfPanel.classList.remove('hidden');
  ui.pdfOverlay.classList.remove('hidden');

  try {
    const blob = await api.fetchPdf(`/api/document-pdf/${encodeURIComponent(fname)}`);
    if (state.pdfBlobUrl) URL.revokeObjectURL(state.pdfBlobUrl);
    state.pdfBlobUrl = URL.createObjectURL(blob);
    ui.pdfIframe.src = state.pdfBlobUrl;
    ui.pdfIframe.onload = () => {
      ui.pdfLoading.classList.add('hidden');
      ui.pdfIframe.classList.remove('hidden');
    };
  } catch (err) {
    ui.pdfLoading.classList.add('hidden');
    ui.documentError.textContent = t('couldNotLoadPdf', { error: err.message });
    ui.documentError.classList.remove('hidden');
    toast(t('couldNotLoadPdf', { error: err.message }), 'error');
  }
}

async function openStructurePanel(fname) {
  ui.pdfTitle.textContent = `${fname} / structured.md`;
  ui.pdfIframe.src = '';
  ui.pdfIframe.classList.add('hidden');
  ui.structureContent.textContent = '';
  ui.structureContent.classList.add('hidden');
  ui.documentError.textContent = '';
  ui.documentError.classList.add('hidden');
  ui.documentLoadingLabel.textContent = t('loadingStructure');
  ui.pdfLoading.classList.remove('hidden');
  ui.pdfPanel.classList.remove('hidden');
  ui.pdfOverlay.classList.remove('hidden');

  try {
    const { ok, data } = await api.documentStructure(fname);
    ui.pdfLoading.classList.add('hidden');
    if (!ok || !data.success) throw new Error(data.error || t('structureRequestFailed'));
    ui.structureContent.textContent = data.structured_md || '';
    ui.structureContent.classList.remove('hidden');
  } catch (err) {
    ui.pdfLoading.classList.add('hidden');
    ui.documentError.textContent = t('couldNotLoadStructure', { error: err.message });
    ui.documentError.classList.remove('hidden');
    toast(t('couldNotLoadStructure', { error: err.message }), 'error');
  }
}

function closePdfPanel() {
  ui.pdfPanel.classList.add('hidden');
  ui.pdfOverlay.classList.add('hidden');
  ui.pdfIframe.src = '';
  ui.structureContent.textContent = '';
  ui.structureContent.classList.add('hidden');
  ui.documentError.textContent = '';
  ui.documentError.classList.add('hidden');
  if (state.pdfBlobUrl) {
    URL.revokeObjectURL(state.pdfBlobUrl);
    state.pdfBlobUrl = null;
  }
}

function toast(message, type = 'info', duration = 3500) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  ui.toastContainer.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

function setAuthMessage(element, message = '', type = 'error') {
  element.textContent = message;
  element.classList.toggle('hidden', !message);
  element.classList.toggle('error', Boolean(message) && type === 'error');
  element.classList.toggle('success', Boolean(message) && type === 'success');
}

function updateLoginRoleUi() {
  const pioLogin = state.loginAccountType === 'pio';
  const signupVisible = !ui.signupForm.classList.contains('hidden');
  ui.authRoleOptions.forEach(button => {
    const active = button.dataset.loginRole === state.loginAccountType;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  ui.loginSubmit.textContent = pioLogin ? 'Sign In as PIO' : 'Sign In as Citizen';
  ui.loginIdentifier.placeholder = pioLogin ? 'Enter PIO email or User ID...' : 'Enter your ID...';
  ui.showSignup.classList.toggle('hidden', pioLogin || signupVisible);
}

function setLoginAccountType(role) {
  state.loginAccountType = role === 'pio' ? 'pio' : 'citizen';
  setAuthMessage(ui.loginError);
  updateLoginRoleUi();
  ui.loginIdentifier.focus();
}

function showAuthView(view = 'login') {
  const signup = view === 'signup';
  ui.authScreen.classList.remove('hidden');
  ui.appShell.classList.add('hidden');
  ui.loginForm.classList.toggle('hidden', signup);
  ui.signupForm.classList.toggle('hidden', !signup);
  ui.authRoleSelector.classList.toggle('hidden', signup);
  ui.showSignup.classList.toggle('hidden', signup || state.loginAccountType === 'pio');
  ui.forgotPassword.classList.toggle('hidden', signup);
  ui.showLogin.classList.toggle('hidden', !signup);
  setAuthMessage(ui.loginError);
  setAuthMessage(ui.signupMessage);
  updateLoginRoleUi();
  setTimeout(() => (signup ? ui.signupName : ui.loginIdentifier).focus(), 0);
}

function showAuthenticatedApp(user = authUser()) {
  state.authenticatedUser = user || null;
  ui.authScreen.classList.add('hidden');
  ui.appShell.classList.remove('hidden');
  ui.signedInName.textContent = user?.fullName || user?.username || 'User';
  ui.signedInAvatar.textContent = user?.role === 'pio' ? 'PIO' : 'Citizen';
  if (user?.role !== 'pio') localStorage.removeItem(PIO_MODE_KEY);
  updatePioModeUi();
}

function handleUnauthorized() {
  state.authenticatedUser = null;
  setPioMode(false);
  clearAuth();
  showAuthView('login');
  setAuthMessage(ui.loginError, 'Your session expired. Please sign in again.');
}

async function handleLogin(event) {
  event.preventDefault();
  const identifier = ui.loginIdentifier.value.trim();
  const password = ui.loginPassword.value;
  setAuthMessage(ui.loginError);
  if (!identifier || !password) {
    setAuthMessage(ui.loginError, 'Enter your User ID/email and password.');
    return;
  }

  ui.loginSubmit.disabled = true;
  ui.loginSubmit.textContent = 'Signing in...';
  try {
    const { ok, data } = await api.login(identifier, password, state.loginAccountType);
    if (!ok || !data.success) throw new Error(data.error || 'Sign in failed.');
    saveAuth(data.token, data.user, ui.rememberLogin.checked);
    showAuthenticatedApp(data.user);
    await initPipeline();
  } catch (error) {
    setAuthMessage(ui.loginError, error.message || 'Sign in failed.');
  } finally {
    ui.loginSubmit.disabled = false;
    updateLoginRoleUi();
  }
}

async function handleSignup(event) {
  event.preventDefault();
  setAuthMessage(ui.signupMessage);
  if (ui.signupPassword.value !== ui.signupConfirm.value) {
    setAuthMessage(ui.signupMessage, 'Passwords do not match.');
    return;
  }

  ui.signupSubmit.disabled = true;
  ui.signupSubmit.textContent = 'Creating account...';
  try {
    const { ok, data } = await api.signup({
      fullName: ui.signupName.value,
      username: ui.signupUsername.value,
      email: ui.signupEmail.value,
      password: ui.signupPassword.value,
    });
    if (!ok || !data.success) throw new Error(data.error || 'Account creation failed.');
    ui.loginIdentifier.value = data.user?.username || ui.signupUsername.value.trim();
    ui.signupForm.reset();
    showAuthView('login');
    setAuthMessage(ui.loginError, 'Account created. You can now sign in.', 'success');
  } catch (error) {
    setAuthMessage(ui.signupMessage, error.message || 'Account creation failed.');
  } finally {
    ui.signupSubmit.disabled = false;
    ui.signupSubmit.textContent = 'Create Account';
  }
}

async function handleLogout() {
  await api.logout().catch(() => {});
  state.authenticatedUser = null;
  setPioMode(false);
  clearAuth();
  ui.loginForm.reset();
  showAuthView('login');
}

function togglePassword(button) {
  const input = $(button.dataset.passwordTarget);
  if (!input) return;
  const reveal = input.type === 'password';
  input.type = reveal ? 'text' : 'password';
  button.textContent = reveal ? 'Hide' : 'Show';
  button.setAttribute('aria-label', reveal ? 'Hide password' : 'Show password');
}

function startNewChat() {
  createConversation(true);
  saveConversations();
  ui.queryInput.value = '';
  ui.queryTiming.textContent = '';
  autoResize();
  renderAll();
  ui.queryInput.focus();
}

function clearActiveChat() {
  const conversation = activeConversation();
  conversation.messages = [];
  conversation.title = 'New chat';
  touchConversation(conversation);
  ui.queryTiming.textContent = '';
  renderAll();
}

function setupEvents() {
  ui.loginForm.addEventListener('submit', handleLogin);
  ui.signupForm.addEventListener('submit', handleSignup);
  ui.showSignup.addEventListener('click', () => showAuthView('signup'));
  ui.showLogin.addEventListener('click', () => showAuthView('login'));
  ui.authRoleOptions.forEach(button => {
    button.addEventListener('click', () => setLoginAccountType(button.dataset.loginRole));
  });
  ui.logoutButton.addEventListener('click', handleLogout);
  ui.forgotPassword.addEventListener('click', () => {
    setAuthMessage(ui.loginError, 'Contact the Chhattisgarh Citizen Helpdesk to reset your password.');
  });
  document.querySelectorAll('[data-password-target]').forEach(button => {
    button.addEventListener('click', () => togglePassword(button));
  });
  ui.newChat.addEventListener('click', startNewChat);
  ui.clearChat.addEventListener('click', clearActiveChat);
  ui.btnInit.addEventListener('click', initPipeline);
  ui.btnSend.addEventListener('click', sendQuery);
  if (ui.uploadPdf && ui.pdfUploadInput) {
    ui.uploadPdf.addEventListener('click', () => {
      if (!state.loading) ui.pdfUploadInput.click();
    });
    ui.pdfUploadInput.addEventListener('change', handlePdfUpload);
  }
  ui.languageOptions.forEach(button => {
    button.addEventListener('click', () => setLanguageMode(button.dataset.languageMode));
  });
  ui.pioModeToggle.addEventListener('change', () => setPioMode(ui.pioModeToggle.checked));
  ui.queryInput.addEventListener('input', autoResize);
  ui.queryInput.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (!ui.btnSend.disabled) sendQuery();
    }
  });

  ui.drawerClose.addEventListener('click', closeDrawer);
  ui.drawerOverlay.addEventListener('click', closeDrawer);
  ui.pdfClose.addEventListener('click', closePdfPanel);
  ui.pdfOverlay.addEventListener('click', closePdfPanel);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      closeDrawer();
      closePdfPanel();
    }
  });
}

async function boot() {
  loadConversations();
  updateLanguageModeUi();
  applyTranslations();
  updatePioModeUi();
  setupEvents();
  renderAll();
  if (authToken()) {
    try {
      const { ok, data } = await api.session();
      if (ok && data.success) {
        showAuthenticatedApp(data.user);
        await initPipeline();
      } else {
        handleUnauthorized();
      }
    } catch (_) {
      handleUnauthorized();
    }
  } else {
    showAuthView('login');
  }
  updateFooterTime();
  setInterval(updateFooterTime, 1000);
}

boot();
