
jQuery.UIBlockStockList = jQuery.UIBlockWithList.extend({

    init: function() {
        this._super("stocks", "table");
        this.submit_name = "Aggiorna il listino DES del produttore";
    },

    rendering_table_post_load_handler: function() {

        var block_obj = this;
        // Init dataTables
        var oTable = this.block_el.find('.dataTable').dataTable({
                'sPaginationType': 'full_numbers', 
                'bLengthChange': true,
                "iDisplayLength": 50,
                "bServerSide": true,
                "bStateSave": true,
                "sAjaxSource": this.get_data_source(),
                "aoColumns": [
                    {"bSearchable":true,"bSortable":true,"sWidth":"10%","bVisible":true},
                    {"bSearchable":true,"bSortable":true,"sWidth":"50%","bVisible":true,"sClass": "left_text"},
                    {"bSearchable":true,"bSortable":true,"sWidth":"20%","bVisible":true,"sClass": "left_text",
                      "fnRender": function ( oObj ) {
                            var _category = oObj.aData[ oObj.iDataColumn ];
                            var _category_list = _category.split('::');
                            var _display_category = _category_list[_category_list.length-1];
                            if (_category_list.length > 1) {
                                _display_category = _category_list[_category_list.length-2] + '::' + _display_category;
                            }
                            return _display_category;
                          },
                       "bUseRendered" : true
                    },
                    {"bSearchable":true, "bSortable":true, "sWidth":"20%", "sType":"currency","sClass": "taright" },
                    {"bSearchable":true,"bSortable":true,"sWidth":"20%", "sClass": "tacenter"}
                ],
                "oLanguage": {
                    "sLengthMenu": gettext("Display _MENU_ records per page"),
                    "sZeroRecords": gettext("Nothing found"),
                    "sInfo": gettext("Showing _START_ to _END_ of _TOTAL_ records"),
                    "sInfoEmpty": gettext("Showing 0 to 0 of 0 records"),
                    "sInfoFiltered": gettext("(filtered from _MAX_ total records)")
                },
                "fnRowCallback": function(nRow, aaData, iDisplayIndex, iDisplayIndexFull) {
                    try {
                        var url = aaData[5];
                        if (url !== undefined) {
                            var _name = aaData[1];
                            res = new jQuery.Resource(url, _name);
                            $(nRow.cells[1]).html( res.render() );
                        }
                    }
                    catch(e){alert(e.message);
                    }
                    return nRow;
                } ,
                "fnFooterCallback": function ( nRow, aaData, iStart, iEnd, aiDisplay ) {
                    /* Modify Django management form info */
                    /* FIXME should not be here this kind of logic computation */
                    $('#' + block_obj.block_box_id + '-form-TOTAL_FORMS').val(iEnd-iStart);
                }
            }); 

        return this._super();

    }

});

jQuery.BLOCKS.stocks = new jQuery.UIBlockStockList();

