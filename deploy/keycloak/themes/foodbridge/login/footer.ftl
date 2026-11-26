<#macro content>
  <footer class="fb-auth-footer">
    <p>Good food. Stronger communities.</p>
    <#if properties.localInboxUrl?has_content>
      <p class="fb-local-inbox">Local preview: emails appear in the <a href="${properties.localInboxUrl}" target="_blank" rel="noopener noreferrer">test inbox</a>.</p>
    </#if>
  </footer>
</#macro>
